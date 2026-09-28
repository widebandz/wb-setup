#!/usr/bin/env python3
"""Local, resumable Wideband setup server.

The browser is a view over allowlisted operations; it is never a general shell.
State lives outside the repository so an upgrade or re-fetch cannot erase a
partially completed build.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import http.client
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
import ssl
import stat
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
FIRST_GOALS = {"research", "website", "proposal"}
AGENT_PROVIDERS = {
    "claude": "Claude Code",
    "codex": "Codex",
    "gemini": "Gemini CLI",
    "grok": "Grok Build",
}
# Only Claude has completed the Wideband iMessage head-agent path. A saved
# preview choice must never start a different (or stale Claude) text runtime.
ACTIVE_AGENT_PROVIDERS = {"claude"}
HANDOFF_VERSION = 1
HANDOFF_FILE_NAMES = (
    "wideband-setup-handoff-v1-01.txt",
    "wideband-setup-handoff-v1-02.txt",
)
HANDOFF_OUTBOX_STATES = ("pending", "processing", "sent", "review", "rejected")
HANDOFF_PROCESSING_STALE_SECONDS = 90  # imsg's 60-second timeout plus margin
HANDOFF_PAGE_MARKERS = {
    "/phone": ("<title>Board ·", "FLEETDECK"),
    "/agent": ("<title>Agent ·", "Talk in Messages"),
    "/project": ("<title>Project ·", "First project"),
    "/graph": ("<title>Knowledge graph ·", "Knowledge graph"),
    "/watch": ("<title>Watch ·", 'aria-label="Head agent terminal"'),
    "/notes": ("<title>Notes beta ·", "Capture an idea"),
}
PHONE_TOKEN_PATTERN = re.compile(r"[0-9a-f]{64}")
PHONE_LINK_PATH_PATTERN = re.compile(r"(/p/[0-9a-f]{64})/phone")
PHONE_ROUTE_PATTERN = re.compile(r"/p/[0-9a-f]{64}(/(?:phone|agent|project|graph|watch|notes|api/watch|api/notes))")
BIND_SUCCESS_OUTPUT = {
    "owner chat bound and first message queued; run installer to activate services",
    "existing owner chat binding verified",
}


def clean_onboarding(body: dict[str, Any]) -> dict[str, str]:
    """Accept display labels, one provider, and a first job, never account data."""
    values: dict[str, str] = {}
    for key, label in (("os_name", "OS name"), ("agent_name", "head agent name")):
        raw = body.get(key)
        if not isinstance(raw, str):
            raise ValueError(f"{label} is required")
        value = raw.strip()
        if not re.fullmatch(r"[\w][\w .'-]{0,59}", value, flags=re.UNICODE):
            raise ValueError(f"{label} must be 1–60 characters and use letters, numbers, spaces, periods, hyphens, or apostrophes")
        values[key] = value
    goal = body.get("first_goal")
    if not isinstance(goal, str) or goal not in FIRST_GOALS:
        raise ValueError("choose a first job")
    values["first_goal"] = goal
    provider = body.get("agent_provider")
    if not isinstance(provider, str) or provider not in AGENT_PROVIDERS:
        raise ValueError("choose Claude Code, Codex, Gemini CLI, or Grok Build")
    values["agent_provider"] = provider
    return values


def require_active_provider(metadata: dict[str, Any]) -> str:
    provider = metadata.get("agent_provider")
    if provider not in AGENT_PROVIDERS:
        raise ValueError("choose a supported head-agent provider")
    if provider not in ACTIVE_AGENT_PROVIDERS:
        raise RuntimeError(
            f"{AGENT_PROVIDERS[provider]} is saved as your provider choice, but its "
            "Wideband iMessage head-agent path is pending runtime verification. "
            "Choose Claude Code to complete the current text setup."
        )
    return provider


def guard_bound_provider_change(provider: str, home: Path | None = None) -> None:
    """Never let a saved choice disagree with an already bound text runtime."""
    path = (home or Path.home()) / ".wideband" / "imessage" / "config.json"
    if not path.exists():
        return
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("inspect the existing private iMessage runtime before changing providers") from exc
    if not isinstance(config, dict):
        raise RuntimeError("inspect the existing private iMessage runtime before changing providers")
    if config.get("binding") and config.get("agent_command") != provider:
        raise RuntimeError(
            "the owner chat is already bound to another head-agent provider; "
            "review and migrate that live runtime before changing providers"
        )


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


def bootstrap_is_ready(client_mode: bool = False) -> bool:
    """Report the actual bare-Mac tool boundary, not merely an identity file."""
    if not (Path.home() / ".sop-vars").is_file():
        return False
    brew_bin = Path("/opt/homebrew/bin")
    tools = ("brew", "python3", "tmux", "imsg") if client_mode else ("git", "jq", "tmux")
    return all((brew_bin / name).is_file() for name in tools)


def bootstrap_status(state_directory: Path, client_mode: bool = False) -> str:
    if client_mode and platform.system() == "Darwin":
        version = platform.mac_ver()[0]
        if version and int(version.split(".")[0]) < 14:
            return "unsupported_macos"
    value = read_first_line(state_directory / "bootstrap-status")
    allowed = {
        "starting",
        "installing_agent",
        "needs_admin_password",
        "needs_developer_tools",
        "needs_developer_tools_selection",
        "needs_developer_tools_update",
        "needs_homebrew_ownership",
        "installing_tools",
        "collecting_identity",
        "needs_attention",
        "ready",
    }
    if value == "ready":
        return "ready" if bootstrap_is_ready(client_mode) else "needs_attention"
    if value in allowed:
        return value
    return "ready" if bootstrap_is_ready(client_mode) else "starting"


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
                "os_name": "",
                "agent_name": "",
                "first_goal": "",
                "agent_provider": "",
            },
            "interview": {},
            "deviations": [],
            "action_runs": {},
            "last_verification": None,
            "live_checks": {"generated_at": None, "checks": []},
            "handoff": {},
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
        for key in ("completed", "metadata", "interview", "action_runs", "live_checks", "handoff"):
            if not isinstance(data.get(key), dict):
                data[key] = defaults[key]
        if not isinstance(data.get("lifecycle"), dict):
            data["lifecycle"] = defaults["lifecycle"]
        if not isinstance(data.get("deviations"), list):
            data["deviations"] = []
        # Pre-picker builds saved names and a first goal but no provider. Those
        # installations used Claude. A fresh build must still require a choice.
        if "agent_provider" not in data["metadata"] and (
            data["completed"].get("identify.name-your-system")
            or all(data["metadata"].get(key) for key in ("os_name", "agent_name", "first_goal"))
        ):
            data["metadata"]["agent_provider"] = "claude"
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
        "run_imessage_install": ["bash", str(ROOT / "install.sh"), "--imessage-only", "--no-verify"],
        "run_verify_quick": ["bash", str(ROOT / "verify.sh"), "--quick", "--json"],
        "run_verify_imessage": ["bash", str(ROOT / "verify.sh"), "--imessage-only", "--json"],
        "run_verify_full": ["bash", str(ROOT / "verify.sh"), "--json"],
        "run_selftest": ["bash", str(ROOT / "selftest.sh")],
        "run_doctor": ["bash", str(ROOT / "doctor.sh")],
        "run_imessage_init": ["/opt/homebrew/bin/python3", str(ROOT / "imessage" / "runtime.py"), "init"],
        "run_imessage_bind": [
            "/usr/bin/open", "-W", "-n", str(Path.home() / "Applications" / "Wideband Agent.app"),
            "--args", "run-background-task", "/opt/homebrew/bin/python3", str(ROOT / "imessage" / "runtime.py"),
            "bind", "--confirm-separate-account",
        ],
        "run_first_goal_apply": ["/opt/homebrew/bin/python3", str(ROOT / "first_goal" / "runner.py"), "apply"],
        "run_first_goal_check": ["/opt/homebrew/bin/python3", str(ROOT / "first_goal" / "runner.py"), "check"],
        "run_phone_install": ["bash", str(ROOT / "install.sh"), "--phone-only", "--no-verify"],
    }

    def __init__(self, store: StateStore):
        self.store = store
        self.jobs: dict[str, dict[str, Any]] = {}
        self.lock = threading.RLock()

    def start(self, action: str) -> dict[str, Any]:
        if action not in self.COMMANDS:
            raise KeyError(action)
        if action in {"run_imessage_init", "run_imessage_bind"}:
            state = self.store.read()
            require_active_provider(state["metadata"])
            if "prepare.create-accounts" not in state["completed"]:
                raise RuntimeError("confirm the separate agent Apple Account first")
            if action == "run_imessage_init":
                clean_onboarding(state["metadata"])
                read_identity_phone(Path.home())
            elif "connect.messages" not in state["completed"]:
                raise RuntimeError("confirm that Messages received a text from your personal phone first")
            elif not (Path(self.COMMANDS[action][3]) / "Contents" / "MacOS" / "Wideband Agent").is_file():
                raise RuntimeError("Wideband Agent is not installed; finish the machine installation first")
            if not (ROOT / "imessage" / "runtime.py").is_file():
                raise RuntimeError("the iMessage runtime is not installed")
        if action in {"run_first_goal_apply", "run_first_goal_check"}:
            state = self.store.read()
            clean_onboarding(state["metadata"])
            verification = effective_verification(state)
            if not step_is_complete(STEPS["prove.messaging"], state, verification_rollup(verification)):
                raise RuntimeError("confirm a real head-agent reply on your phone before preparing the first job")
            if not (ROOT / "first_goal" / "runner.py").is_file():
                raise RuntimeError("the first-job runner is not installed")
        if action == "run_phone_install":
            state = self.store.read()
            if state["action_runs"].get("run_first_goal_apply", {}).get("status") != "complete":
                raise RuntimeError("prepare the first job before installing the Fleetdeck phone view")
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

    @staticmethod
    def _private_handoff_text(path: Path) -> str | None:
        """Read a small owned regular file without following a replacement link."""
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "r", encoding="utf-8") as source:
                info = os.fstat(source.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or info.st_mode & 0o077 or info.st_size > 4096):
                    return None
                return source.read()
        except (OSError, UnicodeError):
            return None

    def _bind_via_agent_app(self, env: dict[str, str]) -> bool:
        """Launch through the app identity that owns Messages Full Disk Access."""
        # Running Contents/MacOS/Wideband Agent directly from the Terminal-hosted
        # engine inherits Terminal's TCC context. LaunchServices gives the app
        # its own grant. `open` can exit 0 even when the app's task fails, so
        # only the exact private runtime success line establishes completion.
        with tempfile.TemporaryDirectory(prefix="bind-handoff-", dir=self.store.directory) as temporary:
            paths = []
            for label in ("stdout", "stderr"):
                fd, name = tempfile.mkstemp(prefix=f"{label}-", dir=temporary)
                os.close(fd)
                paths.append(Path(name))
            stdout_path, stderr_path = paths
            command = [
                *self.COMMANDS["run_imessage_bind"][:4],
                "--stdout", str(stdout_path), "--stderr", str(stderr_path),
                *self.COMMANDS["run_imessage_bind"][4:],
            ]
            try:
                launched = subprocess.run(
                    command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=180, check=False,
                )
            except (OSError, subprocess.SubprocessError):
                return False
            output = self._private_handoff_text(stdout_path)
            errors = self._private_handoff_text(stderr_path)
            return (launched.returncode == 0 and output is not None
                    and output.strip() in BIND_SUCCESS_OUTPUT and errors is not None
                    and not errors.strip())

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
            input_data = None
            if action == "run_imessage_init":
                metadata = self.store.read()["metadata"]
                names = clean_onboarding(metadata)
                input_data = json.dumps({
                    "owner_phone": read_identity_phone(Path.home()),
                    "os_name": names["os_name"],
                    "agent_name": names["agent_name"],
                    "first_goal": names["first_goal"],
                    "agent_command": require_active_provider(names),
                }) + "\n"
            if action == "run_imessage_bind":
                verified = self._bind_via_agent_app(env)
                self._append(job_id, (
                    "Owner-only iMessage chat verified by Wideband Agent.\n" if verified else
                    "Wideband Agent could not verify the owner chat. Check Messages, Full Disk Access, "
                    "and the fresh owner text, then retry.\n"
                ))
                code = 0 if verified else 1
            else:
                process = subprocess.Popen(
                    self.COMMANDS[action],
                    cwd=ROOT,
                    env=env,
                    stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    errors="replace",
                    bufsize=1,
                )
                if input_data is not None:
                    assert process.stdin is not None
                    process.stdin.write(input_data)
                    process.stdin.close()
                assert process.stdout is not None
                for line in process.stdout:
                    self._append(job_id, line)
                code = process.wait()
            if action == "run_imessage_bind" and code == 0:
                self._append(job_id, "\nLoading the bound head-agent services…\n")
                activation = subprocess.Popen(
                    self.COMMANDS["run_imessage_install"], cwd=ROOT, env=env,
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1,
                )
                assert activation.stdout is not None
                for line in activation.stdout:
                    self._append(job_id, line)
                code = activation.wait()
        except Exception as exc:  # the failure must remain visible in the UI
            self._append(job_id, f"\ninstaller runner error: {exc}\n")
            code = 126

        verification = None
        if action in {"run_install", "run_imessage_install", "run_imessage_bind"} and code == 0:
            # Reconciliation and truth are deliberately separate. install.sh
            # reports whether it reached the end; this immediate read-only pass
            # determines which resulting objects are actually healthy.
            try:
                check_command = self.COMMANDS["run_verify_quick"] if action == "run_install" else self.COMMANDS["run_verify_imessage"]
                checked = subprocess.run(
                    check_command,
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

        if action in {"run_verify_quick", "run_verify_full", "run_verify_imessage"}:
            try:
                verification = json.loads(snapshot["output"])
            except json.JSONDecodeError:
                verification = None

        deactivation_cleared = True
        if action in {"run_install", "run_imessage_install", "run_imessage_bind"} and snapshot["status"] == "complete":
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
            if action in {"run_install", "run_imessage_install", "run_imessage_bind"} \
                    and snapshot["status"] == "complete" and deactivation_cleared:
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


def read_identity_phone(home: Path) -> str:
    """Read the private owner number without sourcing shell code or logging it."""
    try:
        lines = (home / ".sop-vars").read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeError("the Wideband identity file is unavailable") from exc
    for line in lines:
        match = re.fullmatch(r"\s*export\s+OPERATOR_PHONE=(.*?)\s*", line)
        if not match:
            continue
        try:
            values = shlex.split(match.group(1), posix=True)
        except ValueError as exc:
            raise RuntimeError("the Wideband owner phone is invalid") from exc
        if len(values) == 1 and re.fullmatch(r"\+[1-9][0-9]{7,14}", values[0]):
            return values[0]
        break
    raise RuntimeError("the Wideband identity file has no valid owner phone")


def private_project_phone_link(home: Path, value: Any, project_port: Any) -> bool:
    """Show a saved project URL only while its current Serve route is private."""
    if not isinstance(value, str) or type(project_port) is not int or not 1024 <= project_port <= 65535:
        return False
    try:
        url = urllib.parse.urlsplit(value)
        tls_port = url.port or 443
    except ValueError:
        return False
    host = url.hostname or ""
    if (url.scheme != "https" or not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+\.ts\.net", host)
            or url.username or url.password or url.query or url.fragment
            or url.netloc != host + (f":{url.port}" if url.port is not None else "")):
        return False
    candidates = (
        Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale"),
        home / "Applications" / "Tailscale.app" / "Contents" / "MacOS" / "Tailscale",
        Path("/opt/homebrew/bin/tailscale"),
    )
    binary = next((path for path in candidates if path.is_file() and os.access(path, os.X_OK)), None)
    if binary is None:
        return False
    try:
        result = subprocess.run(
            [str(binary), "serve", "status", "--json"],
            capture_output=True, text=True, timeout=3, check=False,
            env={**os.environ, "TAILSCALE_BE_CLI": "1"},
        )
        serve = json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    if not isinstance(serve, dict):
        return False
    tcp, web, funnel = (serve.get("TCP"), serve.get("Web"), serve.get("AllowFunnel") or {})
    if not isinstance(tcp, dict) or not isinstance(web, dict) or not isinstance(funnel, dict):
        return False
    hostport = f"{host}:{tls_port}"
    settings = web.get(hostport)
    if (funnel.get(hostport) is True or not isinstance(settings, dict)
            or not isinstance(tcp.get(str(tls_port)), dict)
            or tcp[str(tls_port)].get("HTTPS") is not True):
        return False
    handlers = settings.get("Handlers")
    if not isinstance(handlers, dict):
        return False
    suffix = "" if tls_port == 443 else f":{tls_port}"
    for path, handler in handlers.items():
        if (not isinstance(path, str) or not path.startswith("/")
                or not isinstance(handler, dict)):
            continue
        proxy = handler.get("Proxy")
        if not isinstance(proxy, str) or proxy.rstrip("/") != f"http://127.0.0.1:{project_port}":
            continue
        current = f"https://{host}{suffix}{'' if path == '/' else path}"
        if value.rstrip("/") == current.rstrip("/"):
            return True
    return False


def read_first_goal_status(home: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    """Expose only current, nonsecret first-job status in the authenticated UI."""
    try:
        value = json.loads((home / ".wideband" / "first-goal" / "status.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict) or any(
        value.get(key) != metadata.get(key)
        for key in ("os_name", "agent_name")
    ) or value.get("goal") != metadata.get("first_goal"):
        return {}
    exposed = {key: value.get(key) for key in (
        "goal", "status", "service_id", "local_url", "updated_at"
    ) if key in value}
    if private_project_phone_link(home, value.get("phone_url"), value.get("port")):
        exposed["phone_url"] = value["phone_url"]
    return exposed


def portal_healthz(scheme: str, host: str, port: int) -> bool:
    """Check one fixed endpoint, with normal TLS verification and no redirects."""
    connection: http.client.HTTPConnection
    if scheme == "https":
        connection = http.client.HTTPSConnection(host, port, timeout=4, context=ssl.create_default_context())
    else:
        connection = http.client.HTTPConnection(host, port, timeout=4)
    try:
        connection.request("GET", "/healthz", headers={"Accept": "text/plain"})
        response = connection.getresponse()
        return response.status == 200 and response.read(32).strip() == b"ok"
    except (OSError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def portal_handoff_page(host: str, port: int, path: str) -> bool:
    """Prove each texted Fleetdeck route is this customer portal's HTML page."""
    route = PHONE_ROUTE_PATTERN.fullmatch(path)
    markers = HANDOFF_PAGE_MARKERS.get(route.group(1)) if route else None
    if not markers:
        return False
    connection = http.client.HTTPSConnection(host, port, timeout=4, context=ssl.create_default_context())
    try:
        connection.request("GET", path, headers={"Accept": "text/html"})
        response = connection.getresponse()
        if (response.status != 200
                or (response.getheader("Content-Type") or "").split(";", 1)[0].strip().lower() != "text/html"):
            return False
        body = response.read(64 * 1024 + 1)
        if len(body) > 64 * 1024:
            return False
        html = body.decode("utf-8")
        return all(marker in html for marker in markers)
    except (OSError, UnicodeError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def portal_handoff_api(host: str, port: int, path: str) -> bool:
    """Prove the two dynamic phone views have working read endpoints."""
    route = PHONE_ROUTE_PATTERN.fullmatch(path)
    suffix = route.group(1) if route else None
    if suffix not in ("/api/watch", "/api/notes"):
        return False
    connection = http.client.HTTPSConnection(host, port, timeout=4, context=ssl.create_default_context())
    try:
        connection.request("GET", path, headers={"Accept": "application/json"})
        response = connection.getresponse()
        if (response.status != 200
                or (response.getheader("Content-Type") or "").split(";", 1)[0].strip().lower() != "application/json"):
            return False
        # The notes collection and terminal output can be large. Read only the
        # response envelope; its first keys are fixed by customer-portal.py.
        prefix = response.read(256).decode("utf-8")
        if suffix == "/api/watch":
            return bool(re.match(r'^\s*\{\s*"running"\s*:\s*true\s*,\s*"text"\s*:\s*"', prefix))
        return bool(re.match(r'^\s*\{\s*"notes"\s*:\s*\[', prefix))
    except (OSError, ValueError, UnicodeError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def phone_access_token(home: Path) -> str | None:
    """Read the portal capability only from this owner's private regular file."""
    override = os.environ.get("FLEETDECK_ACCESS_TOKEN_PATH")
    try:
        path = Path(override).expanduser() if override else home / ".wideband" / "fleetdeck" / "phone-access-token"
    except RuntimeError:
        return None
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
                or info.st_size not in (64, 65)):
            return None
        with os.fdopen(fd, "rb") as file:
            fd = -1
            value = file.read(66)
    except OSError:
        return None
    finally:
        if fd != -1:
            os.close(fd)
    if value.endswith(b"\n"):
        value = value[:-1]
    try:
        token = value.decode("ascii")
    except UnicodeError:
        return None
    return token if PHONE_TOKEN_PATTERN.fullmatch(token) else None


def phone_portal_link(
    home: Path,
    state: dict[str, Any],
    *,
    runner: Any = subprocess.run,
    probe: Any = portal_healthz,
    surface_probe: Any = portal_handoff_page,
) -> dict[str, str]:
    """Expose a phone URL only when this Mac's exact HTTPS Serve route works."""
    waiting = lambda detail: {"status": "waiting", "detail": detail}
    attention = lambda detail: {"status": "needs_attention", "detail": detail}
    if state.get("lifecycle", {}).get("deactivated_at"):
        return waiting("Wideband services are paused. Repair them before checking the phone link.")
    if state.get("action_runs", {}).get("run_phone_install", {}).get("status") != "complete":
        return waiting("Install the local Fleetdeck phone view after your first agent reply.")
    config_path = home / "srv" / "fleetdeck" / "config.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        port = config["ports"]["portal"]
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("invalid portal port")
    except (OSError, ValueError, KeyError, TypeError):
        return attention("Fleetdeck portal configuration is unavailable. Repair the phone view.")
    token = phone_access_token(home)
    if token is None:
        return attention("Fleetdeck phone access is unavailable. Repair the phone view.")
    if not probe("http", "127.0.0.1", port):
        return attention("Fleetdeck portal is not answering locally. Repair the phone view.")

    candidates = (
        Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale"),
        home / "Applications" / "Tailscale.app" / "Contents" / "MacOS" / "Tailscale",
        Path("/opt/homebrew/bin/tailscale"),
    )
    binary = next((path for path in candidates if path.is_file() and os.access(path, os.X_OK)), None)
    if binary is None:
        return waiting("Install and sign into Tailscale on this Mac to create a private HTTPS phone link.")

    def read_tailscale(*args: str) -> dict[str, Any] | None:
        try:
            result = runner([str(binary), *args], capture_output=True, text=True, timeout=5,
                            check=False, env={**os.environ, "TAILSCALE_BE_CLI": "1"})
            if result.returncode == 0:
                value = json.loads(result.stdout)
                return value if isinstance(value, dict) else None
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
        return None

    status = read_tailscale("status", "--json") or {}
    self_status = status.get("Self")
    dns_name = self_status.get("DNSName") if isinstance(self_status, dict) else None
    if not isinstance(dns_name, str):
        return waiting("Sign into Tailscale on this Mac, then check the phone link again.")
    dns_name = dns_name.lower().rstrip(".")
    if not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+\.ts\.net", dns_name):
        return waiting("Tailscale has not published this Mac's private DNS name yet.")

    serve = read_tailscale("serve", "status", "--json") or {}
    tcp = serve.get("TCP") or {}
    web = serve.get("Web") or {}
    funnel = serve.get("AllowFunnel") or {}
    if not isinstance(tcp, dict) or not isinstance(web, dict) or not isinstance(funnel, dict):
        return waiting("Tailscale Serve has no verified HTTPS route for Fleetdeck yet.")
    for hostport, settings in web.items():
        if not isinstance(hostport, str) or not isinstance(settings, dict):
            continue
        host, sep, port_text = hostport.lower().rpartition(":")
        if not sep or host != dns_name or not port_text.isdecimal():
            continue
        if funnel.get(hostport) is True:
            return attention("This Fleetdeck route uses public Tailscale Funnel. Disable Funnel before sharing a private phone link.")
        tls_port = int(port_text)
        tls_settings = tcp.get(port_text)
        if not 1 <= tls_port <= 65535 or not isinstance(tls_settings, dict) or tls_settings.get("HTTPS") is not True:
            continue
        handlers = settings.get("Handlers") or {}
        root_handler = handlers.get("/") if isinstance(handlers, dict) else None
        proxy = root_handler.get("Proxy") if isinstance(root_handler, dict) else None
        if not isinstance(proxy, str) or proxy.rstrip("/") != f"http://127.0.0.1:{port}":
            continue
        if not probe("https", dns_name, tls_port):
            return waiting("Tailscale Serve is mapped, but its HTTPS health check failed. Check Tailscale sign-in and HTTPS certificates.")
        if not surface_probe(dns_name, tls_port, f"/p/{token}/phone"):
            return attention("Fleetdeck's private phone page is not answering with this access link. Repair the phone view.")
        suffix = "" if tls_port == 443 else f":{tls_port}"
        return {
            "status": "ready",
            "url": f"https://{dns_name}{suffix}/p/{token}/phone",
            "detail": "Fleetdeck's HTTPS route answered on this Mac. Open it on your phone to confirm phone reachability, then add it to the home screen.",
        }
    return waiting("Tailscale Serve has no HTTPS route to this Fleetdeck portal. Set up Serve, then check again.")


def _handoff_messages(phone_url: str, agent_name: str, os_name: str, tm_shortcut: bool) -> tuple[str, str]:
    """Build short owner-chat texts from one verified private Fleetdeck origin."""
    try:
        url = urllib.parse.urlsplit(phone_url)
        port = url.port
    except ValueError as exc:
        raise RuntimeError("Fleetdeck did not provide a valid private phone link") from exc
    route = PHONE_LINK_PATH_PATTERN.fullmatch(url.path)
    if (url.scheme != "https" or route is None or url.username or url.password
            or url.query or url.fragment or not url.hostname
            or not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+\.ts\.net", url.hostname)):
        raise RuntimeError("Fleetdeck did not provide a valid private phone link")
    if port is not None and not 1 <= port <= 65535:
        raise RuntimeError("Fleetdeck did not provide a valid private phone link")
    if url.netloc != url.hostname + (f":{port}" if port is not None else ""):
        raise RuntimeError("Fleetdeck did not provide a valid private phone link")
    origin = urllib.parse.urlunsplit((url.scheme, url.netloc, "", "", ""))
    prefix = route.group(1)
    dashboard = (
        f"{agent_name} is ready on {os_name}. Save your private Fleetdeck links; "
        "connect Tailscale on your iPhone before opening them.\n"
        f"Dashboard: {phone_url}\n"
        f"Agent: {origin}{prefix}/agent\n"
        f"Project: {origin}{prefix}/project\n"
        f"Knowledge graph: {origin}{prefix}/graph\n"
        f"Live terminal (read only): {origin}{prefix}/watch\n"
        f"Notes (beta): {origin}{prefix}/notes\n"
        "Open the dashboard in Safari, then Share > Add to Home Screen. Pin this chat for the links."
    )
    shortcut = " tm ls is a shortcut after the full Wideband tools are installed." if tm_shortcut else ""
    commands = (
        "iPhone apps:\n"
        "Tailscale: https://apps.apple.com/us/app/tailscale/id1470499037\n"
        "Termius SSH: https://apps.apple.com/us/app/termius-modern-ssh-client/id549039908\n"
        f"Termius SSH host: {url.hostname}; use your Mac login name after enabling Remote Login. "
        f"In its terminal, tmux ls lists sessions; tmux attach -t wb-head joins {agent_name}."
        f"{shortcut}\n"
        "In a separate Mac shell: claude starts a session; claude -c continues the latest one. "
        "Inside Claude, /help shows commands."
    )
    if any(len(message) > 1500 for message in (dashboard, commands)):
        raise RuntimeError("the setup handoff is too long for the guarded text outbox")
    return dashboard, commands


def handoff_delivery_status(home: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Observe only the two setup files; never read their bodies or retry them."""
    receipt = (state.get("handoff") or {}).get("version") == HANDOFF_VERSION
    counts = {
        "total": len(HANDOFF_FILE_NAMES), "sent": 0, "pending": 0,
        "processing": 0, "stale_processing": 0, "review": 0,
        "rejected": 0, "missing": 0, "unsafe": 0,
    }

    def result(status: str) -> dict[str, Any]:
        return {"status": status, **counts}

    def absent() -> dict[str, Any]:
        if receipt:
            counts["missing"] = len(HANDOFF_FILE_NAMES)
            return result("missing")
        return result("not_queued")

    def unsafe() -> dict[str, Any]:
        for key in counts:
            if key != "total":
                counts[key] = 0
        counts["unsafe"] = len(HANDOFF_FILE_NAMES)
        return result("held")

    opened: list[int] = []
    structure_unsafe = False
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)

    def open_private_directory(path: str | Path, parent_fd: int | None = None,
                               *, private: bool = True) -> int:
        nonlocal structure_unsafe
        options = {"dir_fd": parent_fd} if parent_fd is not None else {}
        fd = os.open(path, directory_flags, **options)
        opened.append(fd)
        info = os.fstat(fd)
        forbidden_mode = 0o077 if private else 0o022
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("unsafe handoff outbox directory")
        if info.st_mode & forbidden_mode:
            structure_unsafe = True
        return fd

    try:
        try:
            parent_fd = open_private_directory(home / ".wideband", private=False)
            runtime_fd = open_private_directory("imessage", parent_fd)
            outbox_fd = open_private_directory("outbox", runtime_fd)
        except FileNotFoundError:
            return absent()

        folders: dict[str, int] = {}
        for folder in HANDOFF_OUTBOX_STATES:
            try:
                folders[folder] = open_private_directory(folder, outbox_fd)
            except FileNotFoundError:
                structure_unsafe = True

        locations: dict[str, list[tuple[str, os.stat_result]]] = {
            name: [] for name in HANDOFF_FILE_NAMES
        }
        unsafe_names: set[str] = set()
        for folder, fd in folders.items():
            for name in HANDOFF_FILE_NAMES:
                try:
                    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                except OSError:
                    unsafe_names.add(name)
                    continue
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or info.st_nlink != 1 or info.st_mode & 0o077):
                    unsafe_names.add(name)
                locations[name].append((folder, info))

        for name in HANDOFF_FILE_NAMES:
            positions = locations[name]
            if name in unsafe_names or len(positions) > 1:
                counts["unsafe"] += 1
            elif not positions:
                counts["missing"] += 1
            else:
                folder, info = positions[0]
                if folder in ("pending", "processing"):
                    counts["pending"] += 1
                    if folder == "processing":
                        counts["processing"] += 1
                        # Moving a file into processing changes inode ctime.
                        # Its queued mtime may be much older than this claim.
                        if time.time() - info.st_ctime > HANDOFF_PROCESSING_STALE_SECONDS:
                            counts["stale_processing"] += 1
                else:
                    counts[folder] += 1

        if structure_unsafe:
            # Older runtimes created the outbox root as 0755. There is no
            # delivery to review before any setup file or receipt exists.
            if not receipt and counts["missing"] == counts["total"]:
                counts["missing"] = 0
                return result("not_queued")
            return unsafe()
        if counts["unsafe"] or counts["review"] or counts["stale_processing"]:
            return result("held")
        if counts["rejected"]:
            return result("rejected")
        if counts["missing"] and (receipt or counts["missing"] < counts["total"]):
            return result("missing")
        if counts["sent"] == counts["total"]:
            return result("sent")
        if counts["pending"]:
            return result("pending")
        return result("not_queued")
    except (OSError, ValueError):
        return unsafe()
    finally:
        for fd in reversed(opened):
            os.close(fd)


def confirm_setup_handoff(store: StateStore) -> dict[str, str]:
    """Record an explicit owner action before any setup text is queued."""
    state = store.read()
    require_active_provider(state["metadata"])
    if not state.get("completed", {}).get("prove.phone-board"):
        raise RuntimeError("confirm the Fleetdeck board on the phone before approving setup texts")
    handoff = state.get("handoff") or {}
    if handoff.get("version") == HANDOFF_VERSION:
        return {"status": "already_queued", "approved_at": str(handoff.get("approved_at") or "")}
    approved_at = str(handoff.get("approved_at") or now())

    def remember(data: dict[str, Any]) -> None:
        record = data.setdefault("handoff", {})
        record["approved_at"] = approved_at
        record.setdefault("status", "approved")

    store.update(remember)
    return {"status": "approved", "approved_at": approved_at}


def queue_setup_handoff(
    store: StateStore,
    home: Path | None = None,
    *,
    runner: Any = subprocess.run,
    probe: Any = portal_healthz,
    surface_probe: Any = portal_handoff_page,
    api_probe: Any = portal_handoff_api,
) -> dict[str, Any]:
    """Queue one owner-only handoff through the guarded outbox, never send directly."""
    home = home or Path.home()
    state = store.read()
    names = clean_onboarding(state["metadata"])
    require_active_provider(names)
    if state.get("lifecycle", {}).get("deactivated_at") or (store.directory / "deactivated").exists():
        raise RuntimeError("repair Wideband services before sending the setup handoff")
    if state.get("action_runs", {}).get("run_imessage_bind", {}).get("status") != "complete":
        raise RuntimeError("finish the owner-only iMessage binding before the setup handoff")
    rollup = verification_rollup(effective_verification(state))
    if not step_is_complete(STEPS["prove.messaging"], state, rollup):
        raise RuntimeError("confirm a real agent reply on the phone before the setup handoff")
    if state.get("action_runs", {}).get("run_first_goal_apply", {}).get("status") != "complete":
        raise RuntimeError("prepare the first job before the setup handoff")
    if state.get("action_runs", {}).get("run_phone_install", {}).get("status") != "complete":
        raise RuntimeError("install the Fleetdeck phone view before the setup handoff")
    if not state.get("completed", {}).get("prove.phone-board"):
        raise RuntimeError("confirm the Fleetdeck board works on the phone before the setup handoff")
    if not state.get("handoff", {}).get("approved_at"):
        raise RuntimeError("approve the setup texts in Wideband Setup before they are queued")
    link = phone_portal_link(home, state, runner=runner, probe=probe, surface_probe=surface_probe)
    if link.get("status") != "ready" or not link.get("url"):
        raise RuntimeError("verify the private Fleetdeck HTTPS phone link before the setup handoff")

    runtime_state = home / ".wideband" / "imessage"
    config_text = JobRunner._private_handoff_text(runtime_state / "config.json")
    if config_text is None:
        raise RuntimeError("the private iMessage owner binding is unavailable")
    try:
        config = json.loads(config_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("the private iMessage owner binding is invalid") from exc
    if not isinstance(config, dict):
        raise RuntimeError("the private iMessage owner binding is invalid")
    binding = config.get("binding")
    if (config.get("owner_phone") != read_identity_phone(home)
            or config.get("agent_command") != "claude"
            or config.get("session") != "wb-head"
            or not isinstance(binding, dict)
            or type(binding.get("chat_id")) is not int
            or not isinstance(binding.get("chat_guid"), str) or not binding["chat_guid"]
            or not isinstance(binding.get("account_login"), str) or not binding["account_login"]):
        raise RuntimeError("the private iMessage binding does not match this Claude setup")

    tm = home / "bin" / "tm"
    messages = _handoff_messages(link["url"], names["agent_name"], names["os_name"],
                                 tm.is_file() and os.access(tm, os.X_OK))
    parsed_link = urllib.parse.urlsplit(link["url"])
    host, port = parsed_link.hostname, parsed_link.port or 443
    prefix = parsed_link.path.removesuffix("/phone")
    if not host or any(not surface_probe(host, port, prefix + path) for path in HANDOFF_PAGE_MARKERS):
        raise RuntimeError("verify every Fleetdeck phone page over private HTTPS before the setup handoff")
    if any(not api_probe(host, port, prefix + path) for path in ("/api/watch", "/api/notes")):
        raise RuntimeError("verify Fleetdeck's live terminal and notes read endpoints before the setup handoff")
    outbox = runtime_state / "outbox"
    try:
        root_info = outbox.lstat()
    except OSError as exc:
        raise RuntimeError("the guarded iMessage outbox root is unavailable; repair the iMessage runtime") from exc
    if (not stat.S_ISDIR(root_info.st_mode) or root_info.st_uid != os.getuid()
            or root_info.st_mode & 0o077):
        raise RuntimeError("the guarded iMessage outbox root is unsafe; repair the iMessage runtime")
    for folder in HANDOFF_OUTBOX_STATES:
        path = outbox / folder
        try:
            info = path.lstat()
        except OSError as exc:
            raise RuntimeError("the guarded iMessage outbox is unavailable") from exc
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise RuntimeError("the guarded iMessage outbox has unsafe permissions")

    lock_path = runtime_state / "outbox.lock"
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    lock_fd = os.open(lock_path, flags, 0o600)
    try:
        info = os.fstat(lock_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise RuntimeError("the guarded iMessage outbox lock is unsafe")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        # This receipt also prevents replay if an operator later clears sent
        # files. Fixed filenames cover a crash between queueing and receipt.
        latest = store.read()
        if any(latest.get(key) != state.get(key) for key in (
            "metadata", "completed", "action_runs", "last_verification", "live_checks", "lifecycle"
        )) or (store.directory / "deactivated").exists():
            raise RuntimeError("setup changed while checking the phone handoff; check it again")
        prior_held = {
            name for name in latest.get("handoff", {}).get("held_files", [])
            if name in HANDOFF_FILE_NAMES
        }
        def confirmed_sent(name: str) -> bool:
            try:
                item = (outbox / "sent" / name).lstat()
                return stat.S_ISREG(item.st_mode) and item.st_uid == os.getuid() and item.st_nlink == 1
            except OSError:
                return False

        current_held = set()
        for filename in HANDOFF_FILE_NAMES:
            if any((outbox / folder / filename).exists() or (outbox / folder / filename).is_symlink()
                   for folder in ("review", "rejected")) or any(
                       (outbox / folder / filename).is_symlink() for folder in HANDOFF_OUTBOX_STATES
                   ):
                current_held.add(filename)
        unresolved = sorted(current_held | {
            name for name in prior_held if not confirmed_sent(name)
        })
        if unresolved:
            def remember_held(data: dict[str, Any]) -> None:
                record = data.setdefault("handoff", {})
                record.update({"status": "held", "held_at": now(), "held_files": unresolved})

            store.update(remember_held)
            return {"status": "held", "queued": 0}
        if latest.get("handoff", {}).get("version") == HANDOFF_VERSION:
            delivery = handoff_delivery_status(home, latest)
            if delivery["status"] in ("held", "rejected", "missing"):
                def remember_missing(data: dict[str, Any]) -> None:
                    record = data.setdefault("handoff", {})
                    record.update({
                        "status": "held", "held_at": now(),
                        "held_files": list(HANDOFF_FILE_NAMES),
                    })

                store.update(remember_missing)
                return {"status": "held", "queued": 0}
            return {"status": "already_queued", "queued": 0}
        queued = 0
        for filename, body in zip(HANDOFF_FILE_NAMES, messages):
            if any((outbox / folder / filename).exists() or (outbox / folder / filename).is_symlink()
                   for folder in HANDOFF_OUTBOX_STATES):
                continue
            fd, staged = tempfile.mkstemp(prefix=f".{filename}.", suffix=".tmp", dir=outbox / "pending")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as file:
                    file.write(body + "\n")
                    file.flush()
                    os.fsync(file.fileno())
                    os.fchmod(file.fileno(), 0o600)
                os.link(staged, outbox / "pending" / filename, follow_symlinks=False)
                queued += 1
            finally:
                Path(staged).unlink(missing_ok=True)
        def remember_queued(data: dict[str, Any]) -> None:
            record = data.setdefault("handoff", {})
            record.update({
                "version": HANDOFF_VERSION,
                "status": "queued",
                "queued_at": now(),
                "message_count": len(HANDOFF_FILE_NAMES),
            })
            record.pop("held_files", None)
            record.pop("held_at", None)

        store.update(remember_queued)
        return {"status": "queued" if queued else "already_queued", "queued": queued}
    finally:
        os.close(lock_fd)


def managed_fleetdeck_prefixes(home: Path, org: str) -> list[str]:
    """Find only configured Fleetdeck job prefixes, never a wildcard namespace."""
    prefixes = [f"com.{org}"]
    try:
        config = json.loads((home / "srv" / "fleetdeck" / "config.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return prefixes
    candidate = config.get("label_prefix") if isinstance(config, dict) else None
    if isinstance(candidate, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9.-]{1,99}", candidate) \
            and ".." not in candidate and candidate not in prefixes:
        prefixes.append(candidate)
    return prefixes


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
    labels = [f"com.{org}.{job}" for job in (
        "imessage-watch", "imessage-route", "imessage-outbox", "imessage-keep",
        "cost-watch", "healthcheck", "tmux-boot",
    )]
    labels.append("ai.wideband.first-project")
    for prefix in managed_fleetdeck_prefixes(home, org):
        labels.extend(f"{prefix}.fleetdeck-{job}" for job in ("portal", "chat", "adopt", "skin"))

    for label in dict.fromkeys(labels):
        if run_launchctl and platform.system() == "Darwin":
            target = f"gui/{uid}/{label}"
            result = subprocess.run(
                ["/bin/launchctl", "bootout", target],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=8,
            )
            if result.returncode == 0:
                stopped.append(label)
            for _ in range(20):
                active = subprocess.run(
                    ["/bin/launchctl", "print", target], check=False,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
                ).returncode == 0
                if not active:
                    break
                time.sleep(0.15)
            else:
                raise RuntimeError(f"could not stop managed background job {label}")
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
        data["completed"].pop("prove.messaging", None)
        data["last_verification"] = None
        data["live_checks"] = {"generated_at": None, "checks": []}
        for action in ("run_first_goal_apply", "run_first_goal_check", "run_phone_install"):
            data["action_runs"].pop(action, None)
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
        f"- OS display name: {metadata.get('os_name') or 'Not recorded'}",
        f"- Head agent name: {metadata.get('agent_name') or 'Not recorded'}",
        f"- Head agent provider: {AGENT_PROVIDERS.get(metadata.get('agent_provider'), 'Not recorded')}",
        f"- First job: {metadata.get('first_goal') or 'Not recorded'}",
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

    @staticmethod
    def _claude_executable() -> str | None:
        """Find Claude in the engine's PATH or its usual macOS install paths."""
        cli = shutil.which("claude")
        if cli:
            return str(Path(cli).resolve())
        for candidate in (
            Path.home() / ".local" / "bin" / "claude",
            Path.home() / "bin" / "claude",
            Path("/opt/homebrew/bin/claude"),
            Path("/usr/local/bin/claude"),
        ):
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        return None

    def require_claude_authentication(self) -> None:
        """Check the live CLI login without exposing account data to the UI."""
        cli = self._claude_executable()
        if not cli:
            raise RuntimeError("Claude Code is still installing. Try sign-in again after installation finishes.")
        try:
            result = subprocess.run(
                [cli, "auth", "status", "--json"],
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=10,
                check=False,
            )
            status = json.loads(result.stdout) if result.returncode == 0 else None
        except (OSError, ValueError, subprocess.SubprocessError):
            status = None
        if not isinstance(status, dict) or status.get("loggedIn") is not True:
            raise RuntimeError(
                "Claude Code is not signed in yet. Wait for 'Login successful' in the sign-in window, then try again."
            )

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
  claude auth login
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
    server_version = "WidebandSetup/0.6"

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
                state.setdefault("handoff", {})["delivery"] = handoff_delivery_status(Path.home(), state)
                current_bootstrap_status = bootstrap_status(self.app.store.directory, self.app.client_mode)
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
                            "first_goal": read_first_goal_status(Path.home(), state.get("metadata") or {}),
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
            elif path == "/api/phone-link":
                self._json(HTTPStatus.OK, phone_portal_link(Path.home(), self.app.store.read()))
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
                if complete and step_id == "prepare.create-accounts" and body.get("account_distinct") is not True:
                    raise ValueError("confirm the agent Apple Account is different from the account on your personal iPhone")
                if complete and step_id == "identify.authenticate-agent":
                    require_active_provider(self.app.store.read()["metadata"])
                    self.app.require_claude_authentication()

                def set_step(data: dict[str, Any]) -> None:
                    if complete:
                        if step_id == "identify.authenticate-agent":
                            require_active_provider(data["metadata"])
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

            if path == "/api/onboarding":
                values = clean_onboarding(body)
                if any(job["status"] == "running" and job["action"] in {
                    "run_imessage_init", "run_imessage_bind", "run_first_goal_apply", "run_first_goal_check", "run_phone_install"
                } for job in self.app.runner.summary()):
                    raise RuntimeError("wait for the current head-agent setup task before changing these choices")
                guard_bound_provider_change(values["agent_provider"])

                def save_onboarding(data: dict[str, Any]) -> None:
                    provider_changed = data["metadata"].get("agent_provider", "claude") != values["agent_provider"]
                    changed = any(data["metadata"].get(key) != value for key, value in values.items())
                    data["metadata"].update(values)
                    data["completed"]["identify.name-your-system"] = {"at": now(), "source": "onboarding"}
                    if provider_changed:
                        for step_id in ("identify.authenticate-agent", "connect.imessage-bind", "prove.messaging"):
                            data["completed"].pop(step_id, None)
                    if changed:
                        for action in ("run_imessage_init", "run_imessage_bind", "run_first_goal_apply", "run_first_goal_check", "run_phone_install"):
                            data["action_runs"].pop(action, None)

                state = self.app.store.update(save_onboarding)
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

            if path == "/api/handoff/confirm":
                if body.get("confirm") is not True:
                    raise ValueError("confirm the setup texts before sending them")
                self._json(HTTPStatus.OK, confirm_setup_handoff(self.app.store))
                return

            if path == "/api/handoff":
                self._json(HTTPStatus.OK, queue_setup_handoff(self.app.store))
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
                    require_active_provider(self.app.store.read()["metadata"])
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
