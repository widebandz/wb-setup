#!/usr/bin/env python3
"""Wideband's one-owner iMessage transport.

The agent receives text in a persistent tmux session and writes reply files.
Only this transport may call ``imsg send``. It never accepts an arbitrary
recipient from the agent, and it does not bind a chat until the owner has sent
a fresh message from their phone and confirmed the separate Apple Account.

Commands: init, bind, watch, route, keep, outbox, check.
``init`` reads a JSON object from stdin so addresses do not enter argv/history.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable


SESSION = "wb-head"
MAX_INBOUND = 4000
MAX_REPLY = 1500
MAX_SENDS_PER_HOUR = 12
FRESH_SECONDS = 600
HEAD_STABLE_SECONDS = 8
CLAUDE_ACK_SECONDS = 12
CLAUDE_ACK_POLL_SECONDS = 0.25
MAX_TRANSCRIPTS = 256
MAX_ACK_BYTES = 4 * 1024 * 1024
PHONE_RE = re.compile(r"^\+[1-9][0-9]{7,14}$")
AGENT_COMMANDS = {"claude", "codex"}
FIRST_GOALS = {
    "research": ("Research", "Agree on the question, useful sources, deadline, and answer format."),
    "website": ("Build a website", "Agree on the audience, content, preview, and deployment approval."),
    "proposal": ("Proposal", "Agree on the audience, scope, terms, and approval before sharing."),
}


def private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)


def private_runtime_dir(path: Path) -> None:
    """Create a private runtime directory without following its final component."""
    try:
        existing = path.lstat()
    except FileNotFoundError:
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass  # Recheck with O_NOFOLLOW below if another process created it.
        except OSError as exc:
            raise ValueError(f"private runtime path must be a real directory: {path}") from exc
    except OSError as exc:
        raise ValueError(f"private runtime path must be a real directory: {path}") from exc
    else:
        if not stat.S_ISDIR(existing.st_mode):
            raise ValueError(f"private runtime path must be a real directory: {path}")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise ValueError(f"private runtime path must be a real directory: {path}") from exc
    try:
        os.fchmod(fd, 0o700)
    finally:
        os.close(fd)


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    private_dir(path.parent)
    fd, temp = tempfile.mkstemp(prefix=".wideband-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(value, out, indent=2, sort_keys=True)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def json_lines(text: str) -> list[dict[str, Any]]:
    """imsg emits one JSON object per line for chats, history and watch."""
    out = []
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            out.append(value)
        elif isinstance(value, list):
            out.extend(item for item in value if isinstance(item, dict))
    return out


def normalized_handle(value: Any) -> str:
    value = str(value or "").strip().lower()
    if value.startswith("+"):
        return "+" + "".join(c for c in value[1:] if c.isdigit())
    return value


def fresh_message(value: dict[str, Any], now: float) -> bool:
    raw = value.get("created_at")
    if not isinstance(raw, str):
        return False
    try:
        stamp = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return False
        return 0 <= now - stamp.timestamp() <= FRESH_SECONDS
    except ValueError:
        return False


class Runtime:
    def __init__(
        self,
        home: Path | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.home = (home or Path.home()).expanduser().resolve()
        self.state = self.home / ".wideband" / "imessage"
        self.config_path = self.state / "config.json"
        self.run = runner or subprocess.run
        self._pane_seen: tuple[str, float] | None = None
        self._resolved_tools: dict[str, str] = {}

    def tool_path(self, name: str) -> str:
        """Use the currently verified payload, never another login's PATH."""
        if name in self._resolved_tools:
            return self._resolved_tools[name]
        resolver = self.home / "srv" / "wb-setup" / "lib" / "toolchain-path"
        if resolver.is_file():
            result = subprocess.run(["/bin/bash", str(resolver), name],
                                    capture_output=True, text=True, timeout=30, check=False)
            path = result.stdout.strip()
            if result.returncode or not path.startswith("/") or not Path(path).is_file():
                raise ValueError(f"verified {name} tool is unavailable")
        else:
            # Older standalone operator checkouts retain their prior behavior.
            path = "tmux" if name == "tmux" else (shutil.which(name) or "")
            if not path:
                if name == "imsg":
                    raise ValueError("imsg is not installed; install the messaging tools first")
                raise ValueError(f"{name} tool is unavailable")
        self._resolved_tools[name] = path
        return path

    def config(self) -> dict[str, Any]:
        value = json.loads(self.config_path.read_text(encoding="utf-8"))
        if not PHONE_RE.fullmatch(value.get("owner_phone", "")):
            raise ValueError("invalid owner phone in private runtime config")
        if value.get("session") != SESSION:
            raise ValueError("invalid head session in private runtime config")
        if value.get("agent_command") not in AGENT_COMMANDS:
            raise ValueError("invalid agent command in private runtime config")
        first_goal = value.get("first_goal")
        if first_goal is not None and (not isinstance(first_goal, str) or first_goal not in FIRST_GOALS):
            raise ValueError("invalid first goal in private runtime config")
        return value

    def imsg(self, cfg: dict[str, Any], *args: str, timeout: int = 20) -> subprocess.CompletedProcess[str]:
        return self.run(
            [self.tool_path("imsg"), *args], capture_output=True, text=True,
            timeout=timeout, check=False,
        )

    def tmux(self, *args: str) -> subprocess.CompletedProcess[str]:
        binary = self.tool_path("tmux")
        return self.run([binary, *args], capture_output=True, text=True, timeout=10, check=False)

    @staticmethod
    def legacy_instructions(agent_name: str, os_name: str, outbox: Path) -> str:
        return (
            f"# {agent_name} · {os_name}\n\n"
            "You are the owner's head agent in a persistent tmux session. "
            "Messages from the owner's bound iMessage chat arrive here as prompts.\n\n"
            "For each message, do the work you can safely do, then write one concise "
            "plain-text reply (at most 1500 characters) into a new `.txt` file in "
            f"`{outbox}`. Use a unique filename, write a temporary file first, "
            "and rename it into `outbox` only after the reply is complete. "
            "The guarded Wideband worker sends it only to the bound owner chat. "
            "Never call `imsg send` or choose another recipient. "
            "If approval is needed, ask for it in the reply.\n"
        )

    @classmethod
    def instructions(cls, agent_name: str, os_name: str, outbox: Path) -> str:
        return (
            cls.legacy_instructions(agent_name, os_name, outbox)
            + "\nRead `ARCHITECTURE.md` for the first layered design. Collaborate with "
            "the owner on the selected first job: clarify the desired outcome, "
            "inputs, constraints, and approvals before changing or sharing work. "
            "Treat the selected recipe as a starting point, not authorization. "
            "Keep approved design decisions in this workspace without replacing "
            "the owner's edits.\n"
        )

    @staticmethod
    def architecture(agent_name: str, os_name: str, first_goal: str | None) -> str:
        if first_goal in FIRST_GOALS:
            label, prompt = FIRST_GOALS[first_goal]
            goal = f"{label}. {prompt}"
        else:
            goal = "Choose with the owner. Ask what useful result they want first."
        return (
            f"# {agent_name} · {os_name} — starter architecture\n\n"
            "This is a first design to review with the owner. Record agreed changes "
            "here without treating a setup choice as permission to act.\n\n"
            "1. **Transport and listener:** Messages uses the separate agent Apple "
            "Account; `imsg watch` reads the bound chat and queues new texts.\n"
            "2. **Exact owner router:** Accept only the verified one-to-one owner "
            "chat and deliver its text to the head session.\n"
            "3. **Persistent head agent:** `wb-head` stays in this workspace, "
            "works through owner requests, and writes a concise reply file.\n"
            "4. **Guarded outbox:** The worker validates reply files, limits sends, "
            "and rechecks the bound chat before sending.\n"
            f"5. **Selected first job:** {goal}\n\n"
            "Ask the owner which result matters first and what must be approved. "
            "Refine this design together as the first job takes shape.\n"
        )

    def setup_first_goal(self) -> str | None:
        """Read only the selected recipe from setup's private state, if present."""
        path = self.home / ".wideband" / "setup" / "state.json"
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "r", encoding="utf-8") as source:
                info = os.fstat(source.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or info.st_mode & 0o077 or info.st_size > 64 * 1024):
                    return None
                metadata = json.load(source).get("metadata", {})
            goal = metadata.get("first_goal") if isinstance(metadata, dict) else None
            return goal if goal in FIRST_GOALS else None
        except (OSError, ValueError, TypeError, AttributeError):
            return None

    @staticmethod
    def reconcile_generated(path: Path, new: str, *old_versions: str) -> None:
        """Seed or update only exact generated text; leave client edits intact."""
        if path.is_symlink():
            return
        try:
            current = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            try:
                with path.open("x", encoding="utf-8") as output:
                    output.write(new)
            except FileExistsError:
                pass
            return
        except OSError:
            return
        if current in old_versions and current != new:
            path.write_text(new, encoding="utf-8")

    def ensure_private_queues(self) -> None:
        private_runtime_dir(self.home / ".wideband")
        private_runtime_dir(self.state)
        for root, children in (
            ("inbox", ("pending", "processing", "delivered")),
            ("outbox", ("pending", "processing", "sent", "rejected", "review")),
        ):
            queue_root = self.state / root
            private_runtime_dir(queue_root)
            for child in children:
                private_runtime_dir(queue_root / child)

    def init(self, values: dict[str, Any]) -> str:
        phone = values.get("owner_phone", "")
        if not isinstance(phone, str) or not PHONE_RE.fullmatch(phone):
            raise ValueError("owner_phone must be an E.164 phone number")
        agent = values.get("agent_command", "claude")
        if agent not in AGENT_COMMANDS:
            raise ValueError("agent_command must be claude or codex")
        os_name = str(values.get("os_name") or "Wideband OS").strip()
        agent_name = str(values.get("agent_name") or "Head").strip()
        if any(not s or len(s) > 64 or any(ord(c) < 32 for c in s) for s in (os_name, agent_name)):
            raise ValueError("OS and agent names must be 1–64 printable characters")
        if "first_goal" in values:
            first_goal = values["first_goal"]
            if first_goal is not None and (not isinstance(first_goal, str) or first_goal not in FIRST_GOALS):
                raise ValueError("first_goal must be research, website, or proposal")
        else:
            first_goal = self.setup_first_goal()
        workspace = (self.home / "wideband" / "head").resolve()
        imsg_path = self.tool_path("imsg")
        if self.config_path.exists():
            existing = self.config()
            if existing["owner_phone"] != phone:
                raise ValueError("runtime already belongs to another owner; inspect it before changing identity")
            if existing["agent_command"] != agent:
                raise ValueError(
                    "runtime already uses another head-agent provider; inspect and migrate it "
                    "before changing the active agent"
                )
            self.ensure_private_queues()
            new_os_name = os_name if "os_name" in values else existing["os_name"]
            new_agent_name = agent_name if "agent_name" in values else existing["agent_name"]
            old_goal = existing.get("first_goal")
            new_goal = first_goal if first_goal is not None else old_goal
            changed = (new_os_name != existing["os_name"] or new_agent_name != existing["agent_name"]
                       or new_goal != old_goal)
            workspace = Path(existing["workspace"])
            outbox = workspace / "outbox"
            old_instructions = self.instructions(existing["agent_name"], existing["os_name"], outbox)
            new_instructions = self.instructions(new_agent_name, new_os_name, outbox)
            for name in ("AGENTS.md", "CLAUDE.md"):
                self.reconcile_generated(
                    workspace / name, new_instructions, old_instructions,
                    self.legacy_instructions(existing["agent_name"], existing["os_name"], outbox),
                )
            self.reconcile_generated(
                workspace / "ARCHITECTURE.md",
                self.architecture(new_agent_name, new_os_name, new_goal),
                self.architecture(existing["agent_name"], existing["os_name"], old_goal),
            )
            existing["os_name"] = new_os_name
            existing["agent_name"] = new_agent_name
            existing["first_goal"] = new_goal
            if changed and self.active_agent_pane(existing):
                existing["names_pending_restart"] = True
            atomic_json(self.config_path, existing)
            if existing.get("names_pending_restart"):
                return "head context saved; live head session adopts it on its next start"
            if not changed:
                return "existing private runtime preserved"
            return "head context updated; existing binding and client work preserved"
        cfg = {
            "schema_version": 1,
            "owner_phone": phone,
            "os_name": os_name,
            "agent_name": agent_name,
            "first_goal": first_goal,
            "agent_command": agent,
            "session": SESSION,
            "workspace": str(workspace),
            # Last-known evidence only. Runtime launches resolve the active
            # verified toolchain so an atomic package upgrade does not keep
            # calling the previous version.
            "imsg_path": str(Path(imsg_path).absolute()),
            "binding": None,
            "names_pending_restart": False,
        }
        self.ensure_private_queues()
        workspace.mkdir(parents=True, exist_ok=True)
        # Keep the file outbox under the workspace for the agent. A symlink
        # points only into this user's private runtime, never to Messages data.
        outbox = workspace / "outbox"
        if (outbox.exists() or outbox.is_symlink()) and outbox.resolve() != (self.state / "outbox" / "pending").resolve():
            raise ValueError("workspace already has a different outbox; inspect client work before continuing")
        if not outbox.exists() and not outbox.is_symlink():
            outbox.symlink_to(self.state / "outbox" / "pending", target_is_directory=True)
        instructions = self.instructions(agent_name, os_name, outbox)
        for name in ("AGENTS.md", "CLAUDE.md"):
            path = workspace / name
            if not path.exists():
                path.write_text(instructions, encoding="utf-8")
        architecture = workspace / "ARCHITECTURE.md"
        if not architecture.exists():
            architecture.write_text(self.architecture(agent_name, os_name, first_goal), encoding="utf-8")
        atomic_json(self.config_path, cfg)
        return "private runtime staged; send a fresh text, then bind the owner chat"

    def target_matches(self, cfg: dict[str, Any], live: dict[str, Any], *, binding: dict[str, Any] | None = None) -> bool:
        if live.get("service", "").lower() != "imessage" or live.get("is_group") is not False:
            return False
        if {normalized_handle(p) for p in live.get("participants", [])} != {cfg["owner_phone"]}:
            return False
        if not live.get("guid") or not live.get("account_login"):
            return False
        if binding:
            return (
                live.get("id") == binding["chat_id"]
                and live.get("guid") == binding["chat_guid"]
                and normalized_handle(live.get("account_login")) == normalized_handle(binding["account_login"])
            )
        return True

    def bound_target(self, cfg: dict[str, Any]) -> bool:
        binding = cfg.get("binding")
        if not binding:
            return False
        result = self.imsg(cfg, "group", "--chat-id", str(binding["chat_id"]), "--json")
        return result.returncode == 0 and any(
            self.target_matches(cfg, row, binding=binding) for row in json_lines(result.stdout)
        )

    def bind(self, chat_id: int | None = None, expected_account: str | None = None) -> str:
        if platform.system() != "Darwin" or int(platform.mac_ver()[0].split(".")[0] or 0) < 14:
            raise ValueError("iMessage runtime requires macOS 14 or newer")
        cfg = self.config()
        if cfg.get("binding"):
            if not self.bound_target(cfg):
                raise ValueError("saved chat binding no longer matches the live chat")
            return "existing owner chat binding verified"
        result = self.imsg(cfg, "chats", "--limit", "100", "--json")
        if result.returncode != 0:
            raise ValueError("cannot read Messages chats; approve Full Disk Access for Wideband Agent")
        ids = [int(row["id"]) for row in json_lines(result.stdout) if str(row.get("id", "")).isdigit()]
        if chat_id is not None:
            ids = [value for value in ids if value == chat_id]
        matches: list[dict[str, Any]] = []
        for value in ids:
            group = self.imsg(cfg, "group", "--chat-id", str(value), "--json")
            if group.returncode != 0:
                continue
            for live in json_lines(group.stdout):
                if self.target_matches(cfg, live):
                    if expected_account and normalized_handle(live["account_login"]) != normalized_handle(expected_account):
                        continue
                    matches.append(live)
        if len(matches) != 1:
            raise ValueError(f"expected one exact owner-only iMessage chat; found {len(matches)}")
        live = matches[0]
        history = self.imsg(cfg, "history", "--chat-id", str(live["id"]), "--limit", "1", "--json")
        rows = json_lines(history.stdout) if history.returncode == 0 else []
        first = rows[0] if rows else {}
        if (first.get("is_from_me") is not False
                or normalized_handle(first.get("sender")) != cfg["owner_phone"]
                or first.get("chat_id") != live["id"]
                or not fresh_message(first, time.time())):
            raise ValueError("send a fresh text from the owner's phone, then bind again")
        cfg["binding"] = {
            "chat_id": live["id"], "chat_guid": live["guid"],
            "account_login": live["account_login"],
            "bound_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        atomic_json(self.config_path, cfg)
        self.enqueue(cfg, first)
        atomic_json(self.state / "last-rowid.json", {"rowid": int(first["id"])})
        return "owner chat bound and first message queued; run installer to activate services"

    def enqueue(self, cfg: dict[str, Any], message: dict[str, Any]) -> bool:
        binding = cfg.get("binding")
        if not binding or message.get("is_from_me") is not False:
            return False
        if (message.get("chat_id") != binding["chat_id"]
                or message.get("chat_guid") != binding["chat_guid"]
                or normalized_handle(message.get("sender")) != cfg["owner_phone"]):
            return False
        msg_id = message.get("id")
        guid = message.get("guid")
        body = message.get("text")
        if not isinstance(msg_id, int) or not isinstance(guid, str) or not guid:
            return False
        if not isinstance(body, str) or not body.strip() or len(body) > MAX_INBOUND:
            return False
        key = hashlib.sha256(guid.encode("utf-8")).hexdigest()
        inbox = self.state / "inbox"
        if any((inbox / part / f"{key}.json").exists() for part in ("pending", "processing", "delivered")):
            return False
        atomic_json(inbox / "pending" / f"{key}.json", {
            "id": msg_id, "guid": guid, "sender": cfg["owner_phone"],
            "chat_id": binding["chat_id"], "chat_guid": binding["chat_guid"],
            "text": body, "queued_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        })
        return True

    def active_agent_pane(self, cfg: dict[str, Any]) -> str | None:
        result = self.tmux("list-panes", "-s", "-t", "=" + cfg["session"],
                           "-F", "#{window_active}|#{pane_active}|#{pane_id}|#{pane_current_command}")
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            parts = line.split("|", 3)
            if len(parts) != 4 or parts[0:2] != ["1", "1"]:
                continue
            cmd = parts[3].lower()
            allowed = {"claude", "node"} if cfg["agent_command"] == "claude" else {"codex"}
            if cmd in allowed or (cfg["agent_command"] == "claude" and re.fullmatch(r"\d+\.\d+\.\d+", cmd)):
                return parts[2] if re.fullmatch(r"%\d+", parts[2]) else None
        return None

    def stable_agent_pane(self, cfg: dict[str, Any]) -> str | None:
        """Let a newly opened agent finish its startup screens before typing."""
        pane = self.active_agent_pane(cfg)
        if not pane:
            self._pane_seen = None
            return None
        now = time.monotonic()
        if self._pane_seen is None or self._pane_seen[0] != pane:
            self._pane_seen = (pane, now)
        return pane if now - self._pane_seen[1] >= HEAD_STABLE_SECONDS else None

    def claude_transcript_offsets(self, cfg: dict[str, Any]) -> dict[Path, tuple[int, int]]:
        """Snapshot only the dedicated workspace's Claude session files.

        A pre-send offset means old prompts, including identical text in an
        older session, cannot acknowledge this delivery.  The UUID file name,
        ownership and no-follow open keep unrelated files out of the scan.
        """
        workspace = str(Path(cfg["workspace"]).resolve())
        project = re.sub(r"[^A-Za-z0-9-]", "-", workspace)
        folder = self.home / ".claude" / "projects" / project
        if folder.is_symlink() or not folder.is_dir():
            return {}
        paths = list(folder.glob("*.jsonl"))
        if len(paths) > MAX_TRANSCRIPTS:
            raise ValueError("too many Claude session files in head workspace")
        offsets = {}
        for path in paths:
            try:
                uuid.UUID(path.stem)
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    info = os.fstat(fd)
                    if stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid():
                        offsets[path] = (info.st_ino, info.st_size)
                finally:
                    os.close(fd)
            except (OSError, ValueError):
                continue
        return offsets

    def claude_prompt_recorded(
        self, cfg: dict[str, Any], prompt: str, offsets: dict[Path, tuple[int, int]],
    ) -> bool:
        workspace = str(Path(cfg["workspace"]).resolve())
        current = self.claude_transcript_offsets(cfg)
        for path, (inode, size) in current.items():
            old = offsets.get(path)
            start = old[1] if old and old[0] == inode else 0
            if size <= start or size - start > MAX_ACK_BYTES:
                continue
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    info = os.fstat(fd)
                    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                            or info.st_ino != inode or info.st_size < size):
                        continue
                    os.lseek(fd, start, os.SEEK_SET)
                    data = os.read(fd, size - start)
                finally:
                    os.close(fd)
            except OSError:
                continue
            for line in data.split(b"\n")[:-1]:
                try:
                    row = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    continue
                if not isinstance(row, dict) or row.get("type") != "user":
                    continue
                message = row.get("message")
                if (row.get("cwd") == workspace and row.get("sessionId") == path.stem
                        and isinstance(message, dict) and message.get("role") == "user"
                        and message.get("content") == prompt):
                    return True
        return False

    def wait_for_claude_prompt(
        self, cfg: dict[str, Any], pane: str, prompt: str,
        offsets: dict[Path, tuple[int, int]],
    ) -> bool:
        deadline = time.monotonic() + CLAUDE_ACK_SECONDS
        while True:
            if self.claude_prompt_recorded(cfg, prompt, offsets):
                return True
            if self.active_agent_pane(cfg) != pane or time.monotonic() >= deadline:
                return False
            time.sleep(CLAUDE_ACK_POLL_SECONDS)

    def keep_once(self) -> str:
        cfg = self.config()
        if not cfg.get("binding"):
            return "waiting for owner chat binding"
        if self.active_agent_pane(cfg):
            return "head agent running"
        if self.tmux("has-session", "-t", "=" + cfg["session"]).returncode == 0:
            raise ValueError("head session exists without a recognized agent; inspect it before repair")
        chosen = cfg["agent_command"]
        binary = self.home / ".local" / "bin" / chosen
        if not os.access(binary, os.X_OK):
            resolved = shutil.which(chosen)
            if not resolved:
                raise ValueError(f"{chosen} is not installed or authenticated")
            binary = Path(resolved)
        result = self.tmux("new-session", "-d", "-s", cfg["session"], "-c", cfg["workspace"], str(binary))
        if result.returncode != 0:
            raise ValueError("could not start persistent head session")
        if cfg.get("names_pending_restart"):
            cfg["names_pending_restart"] = False
            atomic_json(self.config_path, cfg)
        return "head session started"

    def route_once(self) -> int:
        cfg = self.config()
        if not cfg.get("binding"):
            return 0
        pending = self.state / "inbox" / "pending"
        processing = self.state / "inbox" / "processing"
        delivered = self.state / "inbox" / "delivered"
        # A previous attempt may have reached the TUI. Never replay it, and
        # preserve message order until an operator resolves the uncertainty.
        if any(processing.glob("*.json")):
            return 0
        count = 0
        def inbound_order(path: Path) -> tuple[int, str]:
            # Filenames are GUID hashes for deduplication, so lexical order
            # does not preserve the conversation. Message ROWID does.
            try:
                rowid = json.loads(path.read_text(encoding="utf-8")).get("id")
                return (rowid if isinstance(rowid, int) else sys.maxsize, path.name)
            except (OSError, ValueError):
                return (sys.maxsize, path.name)

        for path in sorted(pending.glob("*.json"), key=inbound_order):
            pane = self.stable_agent_pane(cfg)
            if not pane:
                break
            if cfg["agent_command"] != "claude":
                raise ValueError("head provider has no prompt acceptance check")
            offsets = self.claude_transcript_offsets(cfg)
            if not offsets:
                # Claude has not initialized its workspace transcript yet.
                break
            claimed = processing / path.name
            try:
                os.replace(path, claimed)
                record = json.loads(claimed.read_text(encoding="utf-8"))
                if (record.get("sender") != cfg["owner_phone"]
                        or record.get("chat_id") != cfg["binding"]["chat_id"]
                        or record.get("chat_guid") != cfg["binding"]["chat_guid"]):
                    raise ValueError("inbox record does not match binding")
                # Newlines and control characters cannot become terminal key
                # presses. The literal prompt has exactly one final Enter.
                body = " ".join(str(record["text"]).split())[:MAX_INBOUND]
                reference = hashlib.sha256(str(record["guid"]).encode("utf-8")).hexdigest()[:12]
                prompt = f"[Owner iMessage #{reference}] {body}"
                if not body or self.tmux("send-keys", "-t", pane, "-l", "--", prompt).returncode != 0:
                    raise ValueError("could not type into head agent pane")
                if self.tmux("send-keys", "-t", pane, "Enter").returncode != 0:
                    raise ValueError("could not submit head agent prompt")
                if not self.wait_for_claude_prompt(cfg, pane, prompt, offsets):
                    raise ValueError("head agent did not record owner prompt; inbox held for review")
                os.replace(claimed, delivered / claimed.name)
                count += 1
                # Give the interactive agent time to finish the current turn
                # before routing another text from the same conversation.
                self._pane_seen = (pane, time.monotonic())
                break
            except Exception:
                # An uncertain send is parked for review, never replayed into
                # a possibly live agent a second time.
                raise
        return count

    def watch(self) -> None:
        cfg = self.config()
        binding = cfg.get("binding")
        if not binding:
            raise ValueError("bind the owner chat before starting the watcher")
        if not self.bound_target(cfg):
            raise ValueError("saved owner chat does not match Messages")
        checkpoint = self.state / "last-rowid.json"
        try:
            last = int(json.loads(checkpoint.read_text())["rowid"])
        except (OSError, ValueError, KeyError, TypeError):
            last = 0
        command = [self.tool_path("imsg"), "watch", "--json", "--chat-id", str(binding["chat_id"]), "--debounce", "500ms"]
        if last:
            command += ["--since-rowid", str(last)]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=sys.stderr, text=True, bufsize=1)
        def stop_watcher(signum: int, _frame: Any) -> None:
            raise SystemExit(128 + signum)

        previous_sigterm = signal.signal(signal.SIGTERM, stop_watcher)
        try:
            assert process.stdout is not None
            for line in process.stdout:
                for message in json_lines(line):
                    if self.enqueue(cfg, message):
                        rowid = int(message["id"])
                        if rowid > last:
                            last = rowid
                            atomic_json(checkpoint, {"rowid": last})
            if process.wait() != 0:
                raise ValueError("imsg watcher exited with an error")
        finally:
            signal.signal(signal.SIGTERM, previous_sigterm)
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if process.stdout is not None:
                process.stdout.close()

    def _rate_ok(self) -> bool:
        path = self.state / "send-rate.json"
        try:
            stamps = json.loads(path.read_text(encoding="utf-8"))["attempts"]
        except (OSError, ValueError, KeyError):
            stamps = []
        now = time.time()
        recent = [float(stamp) for stamp in stamps if now - float(stamp) < 3600]
        if len(recent) >= MAX_SENDS_PER_HOUR:
            return False
        # Count attempts before transport. A crash cannot evade the cap.
        recent.append(now)
        atomic_json(path, {"attempts": recent})
        return True

    def _read_reply(self, path: Path) -> str | None:
        """Read one owned regular file without following a swapped symlink."""
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError:
            return None
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_uid != os.getuid() or info.st_size > 8192):
                return None
            body = os.read(fd, 8193).decode("utf-8").strip()
            if not body or len(body) > MAX_REPLY or any(
                ord(char) < 32 and char not in "\n\t" for char in body
            ):
                return None
            return body
        except (OSError, UnicodeError):
            return None
        finally:
            os.close(fd)

    def outbox_once(self, dry: bool = False) -> int:
        cfg = self.config()
        if not cfg.get("binding"):
            return 0
        lock_path = self.state / "outbox.lock"
        private_dir(self.state)
        with open(lock_path, "a", encoding="utf-8") as lock:
            os.chmod(lock_path, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            pending = self.state / "outbox" / "pending"
            count = 0
            for path in sorted(pending.glob("*.txt")):
                if dry:
                    print(f"{path.name}: {'ready' if self._read_reply(path) is not None else 'reject'}")
                    continue
                claimed = self.state / "outbox" / "processing" / path.name
                os.replace(path, claimed)
                body = self._read_reply(claimed)
                if body is None:
                    os.replace(claimed, self.state / "outbox" / "rejected" / path.name)
                    continue
                if not self.bound_target(cfg):
                    os.replace(claimed, self.state / "outbox" / "review" / path.name)
                    raise ValueError("owner chat changed; outbound message held for review")
                if not self._rate_ok():
                    os.replace(claimed, pending / path.name)
                    break
                result = self.imsg(
                    cfg, "send", "--chat-id", str(cfg["binding"]["chat_id"]),
                    "--service", "imessage", "--text", body, "--json", timeout=60,
                )
                confirmed = result.returncode == 0 and any(
                    row.get("status") == "sent" or row.get("success") is True
                    for row in json_lines(result.stdout)
                )
                # A failed or ambiguous send may have reached Messages. Hold
                # it instead of retrying and possibly sending twice.
                dest = "sent" if confirmed else "review"
                os.replace(claimed, self.state / "outbox" / dest / path.name)
                if not confirmed:
                    raise ValueError("send was not confirmed; outbound message held for review")
                count += 1
            return count

    def check(self) -> dict[str, Any]:
        mac = platform.mac_ver()[0]
        supported = platform.system() == "Darwin" and bool(mac) and int(mac.split(".")[0]) >= 14
        result: dict[str, Any] = {
            "schema_version": 1, "macos_supported": supported,
            "reason": "macOS 14 or newer is required for imsg" if not supported else "",
            "configured": False, "bound": False, "target_verified": False,
            "head_session": False, "imsg_installed": False, "services_loaded": False,
            "names_pending_restart": False,
            "inbox_review_count": len(list((self.state / "inbox" / "processing").glob("*.json"))),
        }
        try:
            cfg = self.config()
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            return result
        result["configured"] = True
        result["bound"] = bool(cfg.get("binding"))
        result["names_pending_restart"] = bool(cfg.get("names_pending_restart"))
        try:
            result["imsg_installed"] = os.access(self.tool_path("imsg"), os.X_OK)
        except ValueError:
            result["imsg_installed"] = False
        if supported and result["bound"] and result["imsg_installed"]:
            result["target_verified"] = self.bound_target(cfg)
        result["head_session"] = bool(self.active_agent_pane(cfg))
        # Labels are supplied by install.sh and may use a client ORG prefix;
        # check for the installed plist names rather than assuming a prefix.
        launch_dir = self.home / "Library" / "LaunchAgents"
        groups: dict[str, set[str]] = {}
        for path in launch_dir.glob("com.*.imessage-*.plist"):
            prefix, sep, job = path.stem.partition(".imessage-")
            if sep:
                groups.setdefault(prefix, set()).add(job)
        jobs = {"watch", "route", "keep", "outbox"}
        for prefix, present in groups.items():
            if not jobs.issubset(present):
                continue
            if all(
                self.run(["launchctl", "print", f"gui/{os.getuid()}/{prefix}.imessage-{job}"],
                         capture_output=True, text=True, timeout=5, check=False).returncode == 0
                for job in jobs
            ):
                result["services_loaded"] = True
                break
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="read private JSON config from stdin; stage workspace")
    bind = commands.add_parser("bind", help="bind a fresh owner-only iMessage chat")
    bind.add_argument("--confirm-separate-account", action="store_true", required=True)
    bind.add_argument("--chat-id", type=int)
    bind.add_argument("--expected-account-stdin", action="store_true")
    for name in ("watch", "route", "keep", "check"):
        commands.add_parser(name)
    outbox = commands.add_parser("outbox")
    outbox.add_argument("--dry", action="store_true")
    args = parser.parse_args()
    runtime = Runtime()
    try:
        if args.command == "init":
            print(runtime.init(json.load(sys.stdin)))
        elif args.command == "bind":
            if not args.confirm_separate_account:
                raise ValueError("confirm the agent Mac uses a separate Apple Account")
            expected = sys.stdin.read().strip() if args.expected_account_stdin else None
            print(runtime.bind(chat_id=args.chat_id, expected_account=expected))
        elif args.command == "watch":
            runtime.watch()
        elif args.command == "route":
            while True:
                runtime.route_once()
                time.sleep(2)
        elif args.command == "keep":
            print(runtime.keep_once())
        elif args.command == "outbox":
            print(f"{runtime.outbox_once(dry=args.dry)} replies sent")
        elif args.command == "check":
            result = runtime.check()
            print(json.dumps(result, sort_keys=True))
            return 0 if all(result.get(key) for key in (
                "macos_supported", "configured", "bound", "target_verified",
                "head_session", "imsg_installed", "services_loaded",
            )) else 1
    except (OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print(f"Wideband iMessage: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
