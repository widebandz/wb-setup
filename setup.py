#!/usr/bin/env python3
"""Local, resumable Wideband setup server.

The browser is a view over allowlisted operations; it is never a general shell.
State lives outside the repository so an upgrade or re-fetch cannot erase a
partially completed build.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import re
import secrets
import shlex
import shutil
import signal
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(os.environ.get("WB_SETUP_ROOT") or Path(__file__).resolve().parent).expanduser().resolve()
INSTALLER = ROOT / "installer"
MANIFEST_PATH = INSTALLER / "manifest.json"
DEFAULT_STATE_DIR = Path(os.environ.get("WB_SETUP_STATE_DIR", "~/.wideband/setup")).expanduser()
MAX_BODY = 128 * 1024
MAX_JOB_OUTPUT = 256 * 1024
SUPPORT_TEXT_LIMIT = 16 * 1024


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def write_private(path: Path, content: str) -> None:
    """Atomically replace a user-owned text artifact with mode 0600."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def private_marker_is(path: Path, expected: str) -> bool:
    try:
        return path.read_text(encoding="utf-8").strip() == expected
    except OSError:
        return False


def read_first_line(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, IndexError):
        return ""


def bootstrap_is_ready() -> bool:
    """Report the actual bare-Mac tool boundary, not merely an identity file."""
    if not (Path.home() / ".sop-vars").is_file():
        return False
    brew_bin = Path("/opt/homebrew/bin")
    return all((brew_bin / name).is_file() for name in ("git", "jq", "tmux"))


def bootstrap_status(state_directory: Path) -> str:
    value = read_first_line(state_directory / "bootstrap-status")
    allowed = {
        "starting",
        "installing_agent",
        "needs_admin_password",
        "installing_tools",
        "collecting_identity",
        "needs_attention",
        "ready",
    }
    if value == "ready":
        return "ready" if bootstrap_is_ready() else "needs_attention"
    if value in allowed:
        return value
    return "ready" if bootstrap_is_ready() else "starting"


def _stop_stale_connection(pid: int, port: int, token: str) -> None:
    """Stop only the authenticated Wideband process described by connection.json."""
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/shutdown",
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json", "X-Wideband-Token": token},
    )
    try:
        with urllib.request.urlopen(request, timeout=1.0) as response:
            response.read()
    except (OSError, urllib.error.URLError):
        # Releases before 0.4.1 do not expose the authenticated shutdown route.
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        try:
            probe = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/health",
                headers={"X-Wideband-Token": token},
            )
            with urllib.request.urlopen(probe, timeout=0.2) as response:
                response.read()
        except (OSError, urllib.error.URLError):
            return
        time.sleep(0.05)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def live_connection(
    state_directory: Path,
    expected_release: str,
    expected_build_id: str,
) -> dict[str, Any] | None:
    """Return a matching local server and replace a healthy but stale release."""
    path = state_directory / "connection.json"
    try:
        connection = json.loads(path.read_text(encoding="utf-8"))
        pid = int(connection["pid"])
        port = int(connection["port"])
        token = str(connection["token"])
        if port < 1 or port > 65535 or not token:
            raise ValueError("invalid connection metadata")
        os.kill(pid, 0)
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/health",
            headers={"X-Wideband-Token": token},
        )
        with urllib.request.urlopen(request, timeout=0.75) as response:
            health = json.loads(response.read().decode("utf-8"))
        if health.get("status") != "ok" or int(health.get("pid", -1)) != pid:
            raise ValueError("unhealthy setup server")
        release_matches = health.get("release") == expected_release
        build_matches = not expected_build_id or health.get("build_id") == expected_build_id
        if release_matches and build_matches:
            return {"pid": pid, "port": port, "token": token}

        # Never interrupt installation or verification already in flight. The
        # next app launch replaces the old server after that task completes.
        state_request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/state",
            headers={"X-Wideband-Token": token},
        )
        try:
            with urllib.request.urlopen(state_request, timeout=0.75) as response:
                server_state = json.loads(response.read().decode("utf-8"))
            if any(job.get("status") == "running" for job in server_state.get("jobs", [])):
                return {"pid": pid, "port": port, "token": token, "stale": True}
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError):
            pass

        _stop_stale_connection(pid, port, token)
        raise ValueError("stale setup server replaced")
    except (OSError, ValueError, KeyError, json.JSONDecodeError, urllib.error.URLError):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return None


def load_manifest() -> dict[str, Any]:
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    ids = [step["id"] for stage in data["stages"] for step in stage["steps"]]
    if len(ids) != len(set(ids)):
        raise RuntimeError("installer manifest contains duplicate step IDs")
    return data


MANIFEST = load_manifest()
STEPS = {step["id"]: step for stage in MANIFEST["stages"] for step in stage["steps"]}
STEP_IDS = set(STEPS)


class StateStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self.path = directory / "state.json"
        self.backups = directory / "backups"
        self.lock = threading.RLock()
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        if not self.path.exists():
            self._write_unlocked(self._new_state())
        else:
            # A running action in persisted state means the previous UI exited
            # before it observed completion. Never present that as still live.
            def interrupt_stale(data: dict[str, Any]) -> None:
                for run in data.get("action_runs", {}).values():
                    if run.get("status") == "running":
                        run["status"] = "interrupted"
                        run["finished_at"] = now()

            self.update(interrupt_stale)

    @staticmethod
    def _new_state() -> dict[str, Any]:
        stamp = now()
        return {
            "schema_version": 1,
            "started_at": stamp,
            "updated_at": stamp,
            "completed": {},
            "metadata": {
                "machine": socket.gethostname().split(".")[0],
                "operator": "",
                "build_date": dt.date.today().isoformat(),
            },
            "interview": {},
            "deviations": [],
            "action_runs": {},
            "last_verification": None,
            "live_checks": {"generated_at": None, "checks": []},
            "lifecycle": {
                "deactivated_at": None,
                "last_reconciled_at": None,
                "last_support_bundle": None,
            },
        }

    @staticmethod
    def _normalize(data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            return StateStore._new_state()
        defaults = StateStore._new_state()
        for key in ("started_at", "updated_at", "last_verification"):
            data.setdefault(key, defaults[key])
        for key in ("completed", "metadata", "interview", "action_runs", "live_checks"):
            if not isinstance(data.get(key), dict):
                data[key] = defaults[key]
        if not isinstance(data.get("lifecycle"), dict):
            data["lifecycle"] = defaults["lifecycle"]
        if not isinstance(data.get("deviations"), list):
            data["deviations"] = []
        for key, value in defaults["metadata"].items():
            data["metadata"].setdefault(key, value)
        for key, value in defaults["lifecycle"].items():
            data["lifecycle"].setdefault(key, value)
        data["schema_version"] = 1
        return data

    def read(self) -> dict[str, Any]:
        with self.lock:
            try:
                data = self._normalize(json.loads(self.path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                corrupt = self.path.with_name(f"state.corrupt-{int(time.time())}.json")
                if self.path.exists():
                    self.path.replace(corrupt)
                data = self._new_state()
                self._write_unlocked(data)
            return data

    def update(self, mutate) -> dict[str, Any]:
        with self.lock:
            data = self.read()
            mutate(data)
            data["updated_at"] = now()
            self._write_unlocked(data)
            return data

    def _write_unlocked(self, data: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix="state.", suffix=".tmp", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)


class JobRunner:
    COMMANDS = {
        "run_install": ["bash", str(ROOT / "install.sh"), "--no-verify"],
        "run_verify_quick": ["bash", str(ROOT / "verify.sh"), "--quick", "--json"],
        "run_verify_full": ["bash", str(ROOT / "verify.sh"), "--json"],
        "run_selftest": ["bash", str(ROOT / "selftest.sh")],
        "run_doctor": ["bash", str(ROOT / "doctor.sh")],
    }

    def __init__(self, store: StateStore):
        self.store = store
        self.jobs: dict[str, dict[str, Any]] = {}
        self.lock = threading.RLock()

    def start(self, action: str) -> dict[str, Any]:
        if action not in self.COMMANDS:
            raise KeyError(action)
        with self.lock:
            running = next((job for job in self.jobs.values() if job["status"] == "running"), None)
            if running:
                raise RuntimeError(f"{running['action']} is already running")
            job_id = secrets.token_hex(6)
            job = {
                "id": job_id,
                "action": action,
                "status": "running",
                "started_at": now(),
                "finished_at": None,
                "exit_code": None,
                "output": "",
            }
            self.jobs[job_id] = job
            self.store.update(
                lambda data: data["action_runs"].update(
                    {
                        action: {
                            "status": "running",
                            "started_at": job["started_at"],
                            "finished_at": None,
                            "exit_code": None,
                            "output_tail": "",
                        }
                    }
                )
            )
            thread = threading.Thread(target=self._run, args=(job_id,), daemon=True)
            thread.start()
            return dict(job)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self.lock:
            job = self.jobs.get(job_id)
            return dict(job) if job else None

    def summary(self) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(job) for job in sorted(self.jobs.values(), key=lambda item: item["started_at"], reverse=True)]

    def _append(self, job_id: str, text: str) -> None:
        with self.lock:
            current = self.jobs[job_id]["output"] + text
            if len(current.encode("utf-8")) > MAX_JOB_OUTPUT:
                current = "[earlier output omitted]\n" + current[-MAX_JOB_OUTPUT:]
            self.jobs[job_id]["output"] = current

    def _run(self, job_id: str) -> None:
        with self.lock:
            action = self.jobs[job_id]["action"]
        env = os.environ.copy()
        env["PATH"] = ":".join(
            [
                str(Path.home() / ".local/bin"),
                str(Path.home() / "bin"),
                "/opt/homebrew/bin",
                "/opt/homebrew/sbin",
                env.get("PATH", ""),
            ]
        )
        try:
            process = subprocess.Popen(
                self.COMMANDS[action],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                bufsize=1,
            )
            assert process.stdout is not None
            for line in process.stdout:
                self._append(job_id, line)
            code = process.wait()
        except Exception as exc:  # the failure must remain visible in the UI
            self._append(job_id, f"\ninstaller runner error: {exc}\n")
            code = 126

        verification = None
        if action == "run_install" and code == 0:
            # Reconciliation and truth are deliberately separate. install.sh
            # reports whether it reached the end; this immediate read-only pass
            # determines which resulting objects are actually healthy.
            try:
                checked = subprocess.run(
                    ["bash", str(ROOT / "verify.sh"), "--quick", "--json"],
                    cwd=ROOT,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    errors="replace",
                    check=False,
                )
                verification = json.loads(checked.stdout)
                summary = verification["summary"]
                self._append(
                    job_id,
                    f"\nPost-install verification: {summary['passed']} passed · "
                    f"{summary['failed']} failed · {summary['skipped']} skipped\n",
                )
            except (OSError, json.JSONDecodeError, KeyError) as exc:
                verification = None
                self._append(job_id, f"\nPost-install verification could not be read: {exc}\n")

        with self.lock:
            job = self.jobs[job_id]
            job["exit_code"] = code
            job["finished_at"] = now()
            # verify intentionally exits with its failure count. It still ran
            # successfully and its structured result is the useful outcome.
            job["status"] = "complete" if code == 0 else "needs_attention"
            snapshot = dict(job)

        if action in {"run_verify_quick", "run_verify_full"}:
            try:
                verification = json.loads(snapshot["output"])
            except json.JSONDecodeError:
                verification = None

        deactivation_cleared = True
        if action == "run_install" and snapshot["status"] == "complete":
            try:
                (self.store.directory / "deactivated").unlink()
            except FileNotFoundError:
                pass
            except OSError:
                deactivation_cleared = False

        def remember(data: dict[str, Any]) -> None:
            data["action_runs"][action] = {
                "status": snapshot["status"],
                "started_at": snapshot["started_at"],
                "finished_at": snapshot["finished_at"],
                "exit_code": snapshot["exit_code"],
                "output_tail": snapshot["output"][-12000:],
            }
            if verification is not None:
                data["last_verification"] = verification
            if action == "run_install" and snapshot["status"] == "complete" and deactivation_cleared:
                data["lifecycle"]["deactivated_at"] = None
                data["lifecycle"]["last_reconciled_at"] = snapshot["finished_at"]

        self.store.update(remember)


INTERVIEW_FIELDS = (
    "name",
    "role",
    "responsibilities",
    "working_style",
    "communication_style",
    "approval_boundaries",
    "never_without_asking",
    "recurring_priorities",
)


def clean_interview(raw: dict[str, Any]) -> dict[str, str]:
    clean: dict[str, str] = {}
    for field in INTERVIEW_FIELDS:
        value = str(raw.get(field, "")).replace("\x00", "").replace("\r\n", "\n").strip()
        clean[field] = value[:4000]
    return clean


def user_markdown(answers: dict[str, str]) -> str:
    def section(title: str, value: str) -> list[str]:
        return [f"## {title}", "", value or "Not specified.", ""]

    lines = [
        "# Operator profile",
        "",
        "This profile was reviewed during the Wideband setup interview.",
        "It describes durable working preferences, not project secrets.",
        "",
    ]
    identity = answers.get("name", "")
    role = answers.get("role", "")
    if role:
        identity = f"{identity} — {role}" if identity else role
    lines += section("Identity", identity)
    lines += section("Responsibilities", answers.get("responsibilities", ""))
    lines += section("How to work with me", answers.get("working_style", ""))
    lines += section("Communication", answers.get("communication_style", ""))
    lines += section("Approval boundaries", answers.get("approval_boundaries", ""))
    lines += section("Never do without asking", answers.get("never_without_asking", ""))
    lines += section("Recurring priorities", answers.get("recurring_priorities", ""))
    result = "\n".join(lines).rstrip() + "\n"
    if len(result.splitlines()) > 200:
        raise ValueError("the generated USER.md exceeds the 200-line cap; shorten the interview answers")
    return result


def verification_rollup(verification: dict[str, Any] | None) -> dict[str, str]:
    grouped: dict[str, list[str]] = {}
    if not verification:
        return {}
    for check in verification.get("checks", []):
        grouped.setdefault(check.get("id", ""), []).append(check.get("status", "skip"))
    result: dict[str, str] = {}
    for check_id, statuses in grouped.items():
        if "fail" in statuses:
            result[check_id] = "fail"
        elif statuses and all(status == "pass" for status in statuses):
            result[check_id] = "pass"
        else:
            result[check_id] = "skip"
    return result


def _parsed_timestamp(value: Any) -> dt.datetime | None:
    text = str(value or "")
    if re.search(r"[+-][0-9]{4}$", text):
        text = text[:-2] + ":" + text[-2:]
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def effective_verification(state: dict[str, Any]) -> dict[str, Any] | None:
    """Merge newer focused checks into the last full verification snapshot."""
    base = state.get("last_verification") or {}
    live = state.get("live_checks") or {}
    base_checks = [dict(item) for item in base.get("checks", []) if isinstance(item, dict)]
    live_checks = [dict(item) for item in live.get("checks", []) if isinstance(item, dict)]
    base_time = _parsed_timestamp(base.get("generated_at"))
    live_time = _parsed_timestamp(live.get("generated_at"))
    use_live = bool(live_checks) and (base_time is None or (live_time is not None and live_time >= base_time))
    if use_live:
        live_ids = {str(item.get("id", "")) for item in live_checks}
        checks = [item for item in base_checks if str(item.get("id", "")) not in live_ids]
        checks.extend(live_checks)
        generated_at = live.get("generated_at") or base.get("generated_at")
    else:
        checks = base_checks
        generated_at = base.get("generated_at")
    if not checks:
        return None
    summary = {
        "passed": sum(item.get("status") == "pass" for item in checks),
        "failed": sum(item.get("status") == "fail" for item in checks),
        "skipped": sum(item.get("status") == "skip" for item in checks),
    }
    return {
        "schema_version": 1,
        "machine": base.get("machine") or socket.gethostname().split(".")[0],
        "generated_at": generated_at,
        "quick": bool(base.get("quick", True)),
        "summary": summary,
        "checks": checks,
    }


def step_is_complete(
    step: dict[str, Any],
    state: dict[str, Any],
    rollup: dict[str, str],
    record_in_progress: bool = False,
) -> bool:
    checks = step.get("checks", [])
    completed = state.get("completed", {})
    if checks:
        statuses = [rollup.get(check, "unknown") for check in checks]
        if "fail" in statuses:
            return False
        if statuses and all(status == "pass" for status in statuses):
            return not step.get("requires_confirmation") or bool(completed.get(step["id"]))
        return False
    if record_in_progress and step["id"] == "prove.record":
        return True
    if completed.get(step["id"]):
        return True
    if step["id"] == "identify.run-bootstrap":
        return (ROOT / "bootstrap.sh").is_file() and (Path.home() / ".sop-vars").is_file()
    action = step.get("action")
    return bool(action and state.get("action_runs", {}).get(action, {}).get("status") == "complete")


def redact_support_text(value: str) -> str:
    """Remove common credentials and personal contact values from support text."""
    result = value.replace(str(Path.home()), "~")
    result = re.sub(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "<email-redacted>", result)
    result = re.sub(r"(?<![A-Za-z0-9])\+[1-9][0-9]{7,14}(?![0-9])", "<phone-redacted>", result)
    result = re.sub(
        r"(?i)\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{12,}|xox[baprs]-[A-Za-z0-9-]{12,})\b",
        "<token-redacted>",
        result,
    )
    result = re.sub(r"(?i)\bbearer\s+[^\s]+", "Bearer <token-redacted>", result)
    result = re.sub(
        r"(?i)\b(password|passwd|token|api[_-]?key|secret)\b\s*[:=]\s*[^\s,;]+",
        r"\1=<redacted>",
        result,
    )
    return result[:SUPPORT_TEXT_LIMIT]


def support_summary(store: StateStore) -> dict[str, Any]:
    """Return a deliberately narrow, secret-free setup snapshot."""
    state = store.read()
    verification = effective_verification(state) or {}
    checks = []
    for item in verification.get("checks", []):
        checks.append(
            {
                "id": str(item.get("id", ""))[:80],
                "status": str(item.get("status", "skip"))[:20],
                "message": redact_support_text(str(item.get("message", ""))),
            }
        )
    actions = {}
    for action, item in state.get("action_runs", {}).items():
        if action not in JobRunner.COMMANDS and action != "deactivate_wideband":
            continue
        actions[action] = {
            "status": item.get("status"),
            "exit_code": item.get("exit_code"),
            "started_at": item.get("started_at"),
            "finished_at": item.get("finished_at"),
        }
    try:
        macos = subprocess.run(
            ["/usr/bin/sw_vers", "-productVersion"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        macos = "unavailable"
    required = [
        step
        for stage in MANIFEST["stages"]
        for step in stage["steps"]
        if not step.get("optional")
    ]
    rollup = verification_rollup(verification)
    completed_ids = sorted(
        step["id"] for step in required if step_is_complete(step, state, rollup)
    )
    lifecycle = state.get("lifecycle", {})
    return {
        "schema_version": 1,
        "generated_at": now(),
        "release": MANIFEST.get("release", "unknown"),
        "manifest_sha256": hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest(),
        "system": {
            "macos": macos or "unavailable",
            "architecture": platform.machine(),
            "python": platform.python_version(),
        },
        "setup": {
            "started_at": state.get("started_at"),
            "updated_at": state.get("updated_at"),
            "completed_required": len(completed_ids),
            "required_total": len(required),
            "completed_step_ids": completed_ids,
            "lifecycle": {
                "deactivated_at": lifecycle.get("deactivated_at"),
                "last_reconciled_at": lifecycle.get("last_reconciled_at"),
                "support_bundle_created": bool(lifecycle.get("last_support_bundle")),
            },
        },
        "actions": actions,
        "verification": {
            "generated_at": verification.get("generated_at"),
            "summary": verification.get("summary") or {"passed": 0, "failed": 0, "skipped": 0},
            "checks": checks,
        },
        "privacy": {
            "excluded": [
                "passwords and tokens",
                "two-factor codes",
                "account profile answers",
                ".sop-vars values",
                "raw command output and logs",
            ]
        },
    }


def support_summary_text(summary: dict[str, Any]) -> str:
    verification = summary["verification"]["summary"]
    setup = summary["setup"]
    lines = [
        "WIDEBAND SETUP DIAGNOSTICS",
        f"Generated: {summary['generated_at']}",
        f"Release: {summary['release']}",
        f"macOS: {summary['system']['macos']} ({summary['system']['architecture']})",
        f"Setup progress: {setup['completed_required']}/{setup['required_total']} required steps",
        (
            "Verification: "
            f"{verification.get('passed', 0)} passed · "
            f"{verification.get('failed', 0)} failed · "
            f"{verification.get('skipped', 0)} deferred"
        ),
        "",
        "Checks needing attention:",
    ]
    attention = [
        item for item in summary["verification"]["checks"] if item["status"] != "pass"
    ]
    lines.extend(
        f"- [{item['id']}] {item['status']}: {item['message']}" for item in attention
    )
    if not attention:
        lines.append("- None in the latest verification.")
    lines += [
        "",
        "Excluded: credentials, 2FA codes, profile answers, .sop-vars values, raw logs.",
    ]
    return "\n".join(lines) + "\n"


def create_support_bundle(store: StateStore) -> tuple[Path, dict[str, Any]]:
    summary = support_summary(store)
    directory = store.directory / "support"
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    destination = directory / f"Wideband-Support-{stamp}.zip"
    fd, temporary = tempfile.mkstemp(prefix="support.", suffix=".zip", dir=directory)
    os.close(fd)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("README.txt", support_summary_text(summary))
            archive.writestr("diagnostics.json", json.dumps(summary, indent=2, sort_keys=True) + "\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    store.update(lambda data: data["lifecycle"].update({"last_support_bundle": str(destination)}))
    return destination, summary


def read_identity_org(home: Path) -> str:
    """Read only the validated ORG assignment; never source the identity file."""
    path = home / ".sop-vars"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeError("the Wideband identity file is unavailable") from exc
    for line in lines:
        match = re.fullmatch(r"\s*export\s+ORG=(.*?)\s*", line)
        if not match:
            continue
        try:
            values = shlex.split(match.group(1), posix=True)
        except ValueError as exc:
            raise RuntimeError("the Wideband identity file has an invalid ORG value") from exc
        if len(values) == 1 and re.fullmatch(r"[a-z][a-z0-9-]{0,30}", values[0]):
            return values[0]
        break
    raise RuntimeError("the Wideband identity file has no valid ORG value")


def deactivate_wideband(
    store: StateStore,
    home: Path | None = None,
    run_launchctl: bool = True,
) -> dict[str, Any]:
    """Stop and recoverably move only the installed Wideband runtime objects."""
    home = home or Path.home()
    org = read_identity_org(home)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    recovery = store.directory / "deactivations" / stamp
    recovery.mkdir(parents=True, exist_ok=False)
    os.chmod(recovery, 0o700)
    moved: list[dict[str, str]] = []
    stopped: list[str] = []
    launch_agents = home / "Library" / "LaunchAgents"
    uid = os.getuid()

    for job in ("cost-watch", "healthcheck", "tmux-boot"):
        label = f"com.{org}.{job}"
        if run_launchctl and platform.system() == "Darwin":
            result = subprocess.run(
                ["/bin/launchctl", "bootout", f"gui/{uid}/{label}"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=8,
            )
            if result.returncode == 0:
                stopped.append(label)
        source = launch_agents / f"{label}.plist"
        if source.exists() or source.is_symlink():
            destination = recovery / "LaunchAgents" / source.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            moved.append({"from": str(source), "to": str(destination)})

    agent = home / "Applications" / "Wideband Agent.app"
    if agent.exists() or agent.is_symlink():
        destination = recovery / "Applications" / agent.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(agent), str(destination))
        moved.append({"from": str(agent), "to": str(destination)})

    finished = now()
    receipt = {
        "schema_version": 1,
        "deactivated_at": finished,
        "organization": org,
        "stopped_labels": stopped,
        "moved": moved,
        "retained": [
            "client workspace and project files",
            "account sign-ins and macOS privacy choices",
            "Wideband setup state and recovery copies",
            "installed command-line tools and operator-owned configuration",
        ],
    }
    write_private(recovery / "receipt.json", json.dumps(receipt, indent=2) + "\n")
    write_private(store.directory / "deactivated", finished + "\n")

    def remember(data: dict[str, Any]) -> None:
        data["lifecycle"]["deactivated_at"] = finished
        data["action_runs"]["deactivate_wideband"] = {
            "status": "complete",
            "started_at": finished,
            "finished_at": finished,
            "exit_code": 0,
            "output_tail": "Wideband background services deactivated; runtime moved to recovery.",
        }

    store.update(remember)
    return {
        "deactivated": True,
        "recovery_path": str(recovery),
        "moved_count": len(moved),
        "stopped_count": len(stopped),
        "retained": receipt["retained"],
    }


def build_record(store: StateStore) -> tuple[Path, str]:
    state = store.read()
    verification = effective_verification(state) or {}
    rollup = verification_rollup(verification)

    required = [
        step
        for stage in MANIFEST["stages"]
        for step in stage["steps"]
        if not step.get("optional")
    ]
    deviations = state.get("deviations", [])
    summary = verification.get("summary") or {}
    metadata = state.get("metadata") or {}
    interview = state.get("interview") or {}
    lines = [
        "# Wideband build record",
        "",
        f"- Machine: {metadata.get('machine') or socket.gethostname().split('.')[0]}",
        f"- Operator: {metadata.get('operator') or interview.get('name') or 'Not recorded'}",
        f"- Build date: {metadata.get('build_date') or dt.date.today().isoformat()}",
        f"- Installer release: {MANIFEST.get('release', 'unknown')}",
        f"- Manifest SHA-256: {hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest()}",
        f"- Setup progress: {sum(1 for step in required if step_is_complete(step, state, rollup, True))}/{len(required)} required steps",
        f"- Last verification: {summary.get('passed', 0)} passed, {summary.get('failed', 0)} failed, {summary.get('skipped', 0)} skipped",
        "",
        "## Deviations",
        "",
    ]
    if deviations:
        for deviation in deviations:
            lines.append(f"- {deviation.get('text', '').strip()} ({deviation.get('created_at', 'date unknown')})")
    else:
        lines.append("- None recorded.")
    lines += ["", "## Incomplete required steps", ""]
    incomplete = [step["title"] for step in required if not step_is_complete(step, state, rollup, True)]
    lines += [f"- {title}" for title in incomplete] or ["- None."]
    failed = [check for check in verification.get("checks", []) if check.get("status") == "fail"]
    lines += ["", "## Verification failures", ""]
    lines += [f"- [{item.get('id')}] {item.get('message')}" for item in failed] or ["- None."]
    lines += ["", "## Handoff", "", "- [ ] Client reviewed the operator profile", "- [ ] Phone surface opened with trusted HTTPS", "- [ ] Test message arrived", "- [ ] First scheduled brief arrived", ""]
    rendered = "\n".join(lines)
    path = store.directory / "build-record.md"
    write_private(path, rendered)
    return path, rendered


class SetupApp:
    AGENT_EXECUTABLE = (
        Path.home() / "Applications" / "Wideband Agent.app" / "Contents" / "MacOS" / "Wideband Agent"
    )
    OPEN_TARGETS = {
        "open_apple_id": "x-apple.systempreferences:com.apple.systempreferences.AppleIDSettings",
        "open_remote_login": "x-apple.systempreferences:com.apple.preferences.sharing?Services_SSH",
        "open_full_disk_access": "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles",
        "open_accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
        "open_screen_recording": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
        "open_screen_sharing": "x-apple.systempreferences:com.apple.preferences.sharing?Services_ScreenSharing",
        "open_login_items": "x-apple.systempreferences:com.apple.LoginItems-Settings.extension",
        "open_tailscale_download": "https://tailscale.com/download/mac",
        "open_github": "https://github.com/signup",
        "open_anthropic": "https://claude.ai/login",
        "open_tailscale_account": "https://login.tailscale.com/admin",
        "open_vercel": "https://vercel.com/login",
        "open_supabase": "https://supabase.com/dashboard",
    }
    OPEN_APPS = {
        "open_messages": "Messages",
        "open_mail": "Mail",
    }

    def __init__(self, store: StateStore, build_id: str = ""):
        self.store = store
        self.runner = JobRunner(store)
        self.token = secrets.token_urlsafe(24)
        self.build_id = build_id
        self.started_at = now()
        self.live_check_lock = threading.Lock()
        self.embedded_mode = os.environ.get("WB_SETUP_EMBEDDED") == "1"
        self.terminal_hosted = os.environ.get("WB_SETUP_TERMINAL_HOSTED") == "1"
        self.client_mode = (
            os.environ.get("WB_SETUP_CLIENT_MODE") == "1"
            or (store.directory / "client-package").is_file()
        )

    @staticmethod
    def _check(check_id: str, status: str, message: str) -> dict[str, str]:
        return {"id": check_id, "status": status, "message": message}

    def refresh_live_checks(self) -> dict[str, Any]:
        """Refresh only the fast client-facing macOS checks without a full verify run."""
        if platform.system() != "Darwin":
            raise RuntimeError("live macOS checks are available only on macOS")
        with self.live_check_lock:
            checks: list[dict[str, str]] = []
            status_path = self.store.directory / "agent-status.json"
            permission_values: dict[str, Any] | None = None
            if self.AGENT_EXECUTABLE.is_file() and os.access(self.AGENT_EXECUTABLE, os.X_OK):
                nonce = f"live-{time.time_ns()}-{secrets.token_hex(4)}"
                app = self.AGENT_EXECUTABLE.parents[2]
                subprocess.run(
                    ["open", "-n", str(app), "--args", "report", nonce],
                    check=False,
                    timeout=10,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline:
                    try:
                        candidate = json.loads(status_path.read_text(encoding="utf-8"))
                        if secrets.compare_digest(str(candidate.get("nonce", "")), nonce):
                            permission_values = candidate
                            break
                    except (OSError, json.JSONDecodeError):
                        pass
                    time.sleep(0.1)

            permission_contract = (
                ("P0-FDA", "full_disk_access", "Wideband Agent has Full Disk Access", "Wideband Agent does not have Full Disk Access"),
                ("P0-AX", "accessibility", "Wideband Agent has Accessibility access", "Wideband Agent does not have Accessibility access"),
                ("P0-SCREEN", "screen_capture", "Wideband Agent has Screen Recording access", "Wideband Agent does not have Screen Recording access"),
                ("P0-AUTOMATION", "automation_messages", "Wideband Agent may automate Messages", "Wideband Agent may not automate Messages"),
            )
            for check_id, key, ready, missing in permission_contract:
                if permission_values is None:
                    checks.append(self._check(check_id, "fail", f"Wideband Agent did not produce a fresh {key.replace('_', ' ')} report"))
                elif permission_values.get(key) is True:
                    checks.append(self._check(check_id, "pass", ready))
                else:
                    checks.append(self._check(check_id, "fail", missing))

            try:
                disabled = subprocess.run(
                    ["/bin/launchctl", "print-disabled", "system"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                ).stdout
            except (OSError, subprocess.SubprocessError):
                disabled = ""

            for check_id, label, ready, missing in (
                ("P0-SSH", "com.openssh.sshd", "Remote Login is on", "Remote Login is off — Settings → General → Sharing → Remote Login"),
                ("P0-SCREENSHARING", "com.apple.screensharing", "Apple Screen Sharing is on", "Apple Screen Sharing is off — Settings → General → Sharing"),
            ):
                if re.search(rf'"{re.escape(label)}"\s*=>\s*enabled', disabled):
                    checks.append(self._check(check_id, "pass", ready))
                elif re.search(rf'"{re.escape(label)}"\s*=>\s*disabled', disabled):
                    checks.append(self._check(check_id, "fail", missing))
                else:
                    checks.append(self._check(check_id, "skip", f"{ready.removesuffix(' is on')} state unreadable"))

            try:
                power = subprocess.run(
                    ["/usr/bin/pmset", "-g"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                ).stdout
            except (OSError, subprocess.SubprocessError):
                power = ""
            if re.search(r"(?m)^\s*sleep\s+0\b", power):
                checks.append(self._check("P0-SLEEP", "pass", "system sleep disabled — scheduled loops will not miss their window"))
            elif power:
                checks.append(self._check("P0-SLEEP", "fail", "system sleeps — 'sudo pmset -a sleep 0' or overnight loops are unreliable"))
            else:
                checks.append(self._check("P0-SLEEP", "skip", "system sleep state unreadable"))

            report = {"generated_at": now(), "checks": checks}
            self.store.update(lambda data: data.update({"live_checks": report}))
            return report

    def open_target(self, action: str) -> None:
        target = self.OPEN_TARGETS[action]
        if platform.system() != "Darwin":
            raise RuntimeError("System Settings links are available only on macOS")
        subprocess.run(["open", target], check=True, timeout=10)

    def open_app(self, action: str) -> None:
        if platform.system() != "Darwin":
            raise RuntimeError("Application links are available only on macOS")
        subprocess.run(["open", "-a", self.OPEN_APPS[action]], check=True, timeout=10)

    def open_claude_auth(self) -> None:
        """Open one fixed Terminal helper; never accept shell text from HTTP."""
        if platform.system() != "Darwin":
            raise RuntimeError("Claude sign-in guidance is available only on macOS")
        helper = self.store.directory / "claude-sign-in.command"
        write_private(
            helper,
            """#!/bin/bash
export PATH="$HOME/.local/bin:$HOME/bin:/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"
clear
printf '\\n  WIDEBAND · CLAUDE SIGN-IN\\n\\n'
printf '  Claude will open a secure browser sign-in. Wideband never sees your password.\\n\\n'
if command -v claude >/dev/null 2>&1; then
  claude
else
  printf '  Claude Code is still installing. Return to Wideband Setup and try again shortly.\\n'
fi
printf '\\n  You may close this window after sign-in.\\n'
""",
        )
        os.chmod(helper, 0o700)
        subprocess.run(["open", "-a", "Terminal", str(helper)], check=True, timeout=10)

    def request_permission(self, command: str) -> None:
        if platform.system() != "Darwin":
            raise RuntimeError("macOS permission requests are available only on macOS")
        if command not in {
            "request-accessibility",
            "request-full-disk",
            "request-messages-automation",
            "request-screen-capture",
        }:
            raise RuntimeError("unknown Wideband permission request")
        if not self.AGENT_EXECUTABLE.is_file() or not os.access(self.AGENT_EXECUTABLE, os.X_OK):
            raise RuntimeError("Wideband Agent is not installed; reopen the packaged Wideband Setup app")
        # Launch through LaunchServices so macOS attributes the consent prompt
        # to the app bundle, not to the Python/Terminal process hosting setup.
        app = self.AGENT_EXECUTABLE.parents[2]
        subprocess.run(
            ["open", "-n", str(app), "--args", command],
            check=True,
            timeout=10,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def reveal_agent(self) -> None:
        if platform.system() != "Darwin":
            raise RuntimeError("Wideband Agent is available only on macOS")
        app = self.AGENT_EXECUTABLE.parents[2]
        if not app.is_dir():
            raise RuntimeError("Wideband Agent is not installed; reopen the packaged Wideband Setup app")
        subprocess.run(["open", "-R", str(app)], check=True, timeout=10)

    @staticmethod
    def reveal_path(path: Path) -> None:
        if platform.system() != "Darwin":
            return
        subprocess.run(["open", "-R", str(path)], check=True, timeout=10)

    def export_support_bundle(self) -> tuple[Path, dict[str, Any]]:
        path, summary = create_support_bundle(self.store)
        self.reveal_path(path)
        return path, summary

    def deactivate(self) -> dict[str, Any]:
        if any(job["status"] == "running" for job in self.runner.summary()):
            raise RuntimeError("wait for the current setup task to finish before deactivating Wideband")
        return deactivate_wideband(self.store)


class LoopbackHTTPServer(ThreadingHTTPServer):
    """Bind locally without HTTPServer's unnecessary reverse-DNS lookup.

    Python's default HTTPServer.server_bind calls socket.getfqdn() after the
    socket is already bound. On current macOS that lookup can provoke a Local
    Network privacy prompt even though Wideband listens only on 127.0.0.1.
    """

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        self.server_name = "localhost"
        self.server_port = self.server_address[1]


class Handler(BaseHTTPRequestHandler):
    app: SetupApp
    server_version = "WidebandSetup/0.5"

    def log_message(self, fmt: str, *args: Any) -> None:
        # Routine polling is intentionally silent: on a bare Mac this server
        # shares Terminal with bootstrap, and request logs must never bury the
        # one administrator-password prompt. Keep HTTP errors visible.
        try:
            status = int(args[1])
        except (IndexError, TypeError, ValueError):
            status = 500
        if status >= 400:
            sys.stderr.write("setup: " + fmt % args + "\n")

    def _headers(self, status: int, content_type: str, length: int | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.end_headers()

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def _authorized(self) -> bool:
        return secrets.compare_digest(self.headers.get("X-Wideband-Token", ""), self.app.token)

    def _require_auth(self) -> bool:
        if self._authorized():
            return True
        self._json(HTTPStatus.UNAUTHORIZED, {"error": "missing or invalid local setup token"})
        return False

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid content length") from exc
        if length < 0 or length > MAX_BODY:
            raise ValueError("request body is too large")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        return value

    def do_GET(self) -> None:  # noqa: N802
        path = urllib.parse.urlsplit(self.path).path
        if path.startswith("/api/"):
            if not self._require_auth():
                return
            if path == "/api/manifest":
                self._json(HTTPStatus.OK, MANIFEST)
            elif path == "/api/health":
                self._json(
                    HTTPStatus.OK,
                    {
                        "status": "ok",
                        "pid": os.getpid(),
                        "release": MANIFEST.get("release", ""),
                        "build_id": self.app.build_id,
                        "started_at": self.app.started_at,
                    },
                )
            elif path == "/api/state":
                state = self.app.store.read()
                effective = effective_verification(state)
                state["last_verification"] = effective
                current_bootstrap_status = bootstrap_status(self.app.store.directory)
                self._json(
                    HTTPStatus.OK,
                    {
                        "state": state,
                        "jobs": self.app.runner.summary(),
                        "facts": {
                            "bootstrap_ready": current_bootstrap_status == "ready",
                            "bootstrap_status": current_bootstrap_status,
                            "client_mode": self.app.client_mode,
                            "embedded_mode": self.app.embedded_mode,
                            "terminal_hosted": self.app.terminal_hosted,
                            "client_name": str(os.environ.get("CLIENT_NAME", ""))[:120],
                            "personalized": private_marker_is(
                                self.app.store.directory / "client-package-kind", "personalized"
                            ),
                            "wideband_agent_installed": self.app.AGENT_EXECUTABLE.is_file(),
                            "setup_app_installed": (
                                Path.home() / "Applications" / "Wideband Setup.app"
                            ).is_dir() or Path("/Applications/Wideband Setup.app").is_dir(),
                            "live_checks_at": (state.get("live_checks") or {}).get("generated_at"),
                            "deactivated": bool(state.get("lifecycle", {}).get("deactivated_at"))
                            or (self.app.store.directory / "deactivated").is_file(),
                        },
                        "verification_rollup": verification_rollup(effective),
                        "connection": {
                            "host": "127.0.0.1",
                            "port": self.server.server_address[1],
                            "release": MANIFEST.get("release", ""),
                            "build_id": self.app.build_id,
                            "started_at": self.app.started_at,
                        },
                    },
                )
            elif path.startswith("/api/jobs/"):
                job = self.app.runner.get(path.rsplit("/", 1)[-1])
                self._json(HTTPStatus.OK if job else HTTPStatus.NOT_FOUND, job or {"error": "job not found"})
            elif path == "/api/support-summary":
                summary = support_summary(self.app.store)
                self._json(
                    HTTPStatus.OK,
                    {"summary": summary, "text": support_summary_text(summary)},
                )
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return

        files = {
            "/": (INSTALLER / "index.html", "text/html; charset=utf-8"),
            "/index.html": (INSTALLER / "index.html", "text/html; charset=utf-8"),
            "/app.js": (INSTALLER / "app.js", "text/javascript; charset=utf-8"),
            "/styles.css": (INSTALLER / "styles.css", "text/css; charset=utf-8"),
            "/wideband-mark.png": (INSTALLER / "wideband-mark.png", "image/png"),
            "/favicon.ico": (INSTALLER / "wideband-mark.png", "image/png"),
            "/apple-touch-icon.png": (INSTALLER / "wideband-mark.png", "image/png"),
            "/apple-touch-icon-precomposed.png": (INSTALLER / "wideband-mark.png", "image/png"),
            "/fonts/inter-latin.woff2": (INSTALLER / "fonts" / "inter-latin.woff2", "font/woff2"),
            "/fonts/orbitron-latin.woff2": (INSTALLER / "fonts" / "orbitron-latin.woff2", "font/woff2"),
        }
        item = files.get(path)
        if not item or not item[0].is_file():
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        body = item[0].read_bytes()
        self._headers(HTTPStatus.OK, item[1], len(body))
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if not self._require_auth():
            return
        path = urllib.parse.urlsplit(self.path).path
        try:
            body = self._body()
            if path == "/api/shutdown":
                self._json(HTTPStatus.OK, {"status": "stopping"})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return

            if path.startswith("/api/steps/"):
                step_id = urllib.parse.unquote(path[len("/api/steps/") :])
                if step_id not in STEP_IDS:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "unknown step"})
                    return
                step = STEPS[step_id]
                confirmable = step.get("type") in {"guided", "interview"} and (
                    not step.get("checks") or step.get("requires_confirmation")
                )
                if step_id == "identify.operator-interview" or not confirmable:
                    raise ValueError("this step is completed by its installer action or verification check")
                complete = bool(body.get("complete"))

                def set_step(data: dict[str, Any]) -> None:
                    if complete:
                        data["completed"][step_id] = {"at": now(), "source": "human"}
                    else:
                        data["completed"].pop(step_id, None)

                state = self.app.store.update(set_step)
                self._json(HTTPStatus.OK, {"completed": state["completed"]})
                return

            if path == "/api/metadata":
                allowed = {
                    key: str(body.get(key, "")).replace("\r", " ").replace("\n", " ")[:200].strip()
                    for key in ("machine", "operator", "build_date")
                }
                state = self.app.store.update(lambda data: data["metadata"].update(allowed))
                self._json(HTTPStatus.OK, {"metadata": state["metadata"]})
                return

            if path == "/api/deviations":
                text = str(body.get("text", "")).strip()[:2000]
                if not text:
                    raise ValueError("deviation text is required")
                state = self.app.store.update(lambda data: data["deviations"].append({"text": text, "created_at": now()}))
                self._json(HTTPStatus.OK, {"deviations": state["deviations"]})
                return

            if path == "/api/interview/preview":
                answers = clean_interview(body)
                self._json(HTTPStatus.OK, {"markdown": user_markdown(answers), "line_count": len(user_markdown(answers).splitlines())})
                return

            if path == "/api/interview/apply":
                answers = clean_interview(body)
                if not answers["name"]:
                    raise ValueError("operator name is required before installing the profile")
                rendered = user_markdown(answers)
                destination = Path.home() / ".claude" / "USER.md"
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    self.app.store.backups.mkdir(parents=True, exist_ok=True)
                    os.chmod(self.app.store.backups, 0o700)
                    backup = self.app.store.backups / f"USER.md.{time.time_ns()}"
                    shutil.copy2(destination, backup)
                write_private(destination, rendered)

                def save_interview(data: dict[str, Any]) -> None:
                    data["interview"] = answers
                    data["completed"]["identify.operator-interview"] = {"at": now(), "source": "interview"}

                self.app.store.update(save_interview)
                self._json(HTTPStatus.OK, {"path": str(destination), "line_count": len(rendered.splitlines())})
                return

            if path == "/api/build-record":
                record_path, rendered = build_record(self.app.store)
                self.app.store.update(
                    lambda data: data["completed"].update(
                        {"prove.record": {"at": now(), "source": "generated-record"}}
                    )
                )
                self._json(HTTPStatus.OK, {"path": str(record_path), "markdown": rendered})
                return

            if path == "/api/support-bundle":
                bundle_path, summary = self.app.export_support_bundle()
                self._json(
                    HTTPStatus.OK,
                    {
                        "path": str(bundle_path),
                        "verification": summary["verification"]["summary"],
                        "privacy": summary["privacy"],
                    },
                )
                return

            if path == "/api/live-checks":
                report = self.app.refresh_live_checks()
                state = self.app.store.read()
                effective = effective_verification(state)
                self._json(
                    HTTPStatus.OK,
                    {
                        "live_checks": report,
                        "verification": effective,
                        "verification_rollup": verification_rollup(effective),
                    },
                )
                return

            if path == "/api/deactivate":
                if body.get("confirm") != "DEACTIVATE":
                    raise ValueError("type DEACTIVATE to confirm")
                self._json(HTTPStatus.OK, self.app.deactivate())
                return

            if path.startswith("/api/actions/"):
                action = path.rsplit("/", 1)[-1]
                if action in self.app.OPEN_TARGETS:
                    self.app.open_target(action)
                    self._json(HTTPStatus.OK, {"opened": action})
                elif action in self.app.OPEN_APPS:
                    self.app.open_app(action)
                    self._json(HTTPStatus.OK, {"opened": action})
                elif action == "open_claude_auth":
                    self.app.open_claude_auth()
                    self._json(HTTPStatus.OK, {"opened": action})
                elif action == "reveal_wideband_agent":
                    self.app.reveal_agent()
                    self._json(HTTPStatus.OK, {"opened": action})
                elif action in {
                    "request_accessibility",
                    "request_full_disk_access",
                    "request_messages_automation",
                    "request_screen_recording",
                }:
                    command = {
                        "request_accessibility": "request-accessibility",
                        "request_full_disk_access": "request-full-disk",
                        "request_messages_automation": "request-messages-automation",
                        "request_screen_recording": "request-screen-capture",
                    }[action]
                    self.app.request_permission(command)
                    self._json(HTTPStatus.OK, {"opened": action})
                elif action in self.app.runner.COMMANDS:
                    self._json(HTTPStatus.ACCEPTED, self.app.runner.start(action))
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "unknown action"})
                return

            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except KeyError:
            self._json(HTTPStatus.NOT_FOUND, {"error": "unknown action"})
        except RuntimeError as exc:
            self._json(HTTPStatus.CONFLICT, {"error": str(exc)})
        except (OSError, subprocess.SubprocessError) as exc:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})


def serve(args: argparse.Namespace) -> None:
    state_directory = Path(args.state_dir).expanduser()
    build_id = read_first_line(state_directory / "payload-build")
    existing = live_connection(state_directory, str(MANIFEST.get("release", "")), build_id)
    if existing:
        url = f"http://127.0.0.1:{existing['port']}/#{existing['token']}"
        if args.no_open:
            print(
                f"Wideband Setup is already running privately on this Mac (port {existing['port']}; the app supplies access).",
                flush=True,
            )
        else:
            print(f"Wideband Setup is already open privately on this Mac (port {existing['port']}).", flush=True)
        if existing.get("stale"):
            print(
                "A setup task is still running on the previous release; reopen the app after it finishes to update.",
                file=sys.stderr,
            )
        if not args.no_open:
            webbrowser.open(url)
        return

    store = StateStore(state_directory)
    app = SetupApp(store, build_id)
    Handler.app = app
    requested = args.port
    try:
        server = LoopbackHTTPServer(("127.0.0.1", requested), Handler)
    except OSError:
        if requested == 0:
            raise
        server = LoopbackHTTPServer(("127.0.0.1", 0), Handler)
        print(f"Port {requested} is busy; selected an available local port.", file=sys.stderr)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/#{app.token}"
    connection_path = store.directory / "connection.json"
    write_private(
        connection_path,
        json.dumps(
            {
                "pid": os.getpid(),
                "port": port,
                "token": app.token,
                "release": MANIFEST.get("release", ""),
                "build_id": app.build_id,
                "started_at": app.started_at,
            }
        )
        + "\n",
    )
    if args.no_open:
        print(f"Wideband Setup is ready privately on this Mac (port {port}; the app supplies access).", flush=True)
    else:
        print(f"Wideband Setup is opening privately on this Mac (port {port}).", flush=True)
    print(f"State: {store.path}", flush=True)
    if not args.no_open:
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nWideband Setup stopped.")
    finally:
        server.server_close()
        try:
            current = json.loads(connection_path.read_text(encoding="utf-8"))
            if secrets.compare_digest(str(current.get("token", "")), app.token):
                connection_path.unlink()
        except (OSError, json.JSONDecodeError):
            pass
        if app.terminal_hosted:
            try:
                (store.directory / "terminal-hosted").unlink()
            except OSError:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Wideband guided installer")
    parser.add_argument("--port", type=int, default=8803, help="local port (default: 8803; falls back when busy)")
    parser.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR), help=argparse.SUPPRESS)
    parser.add_argument("--no-open", action="store_true", help="do not open a browser")
    args = parser.parse_args()
    serve(args)


if __name__ == "__main__":
    main()
