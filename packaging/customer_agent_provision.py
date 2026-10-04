"""Owner-only agent creation, activation, and observed provider process receipts.

The v1 roster records intent; private per-agent manifests hold launch ownership,
instructions, and recovery. No local agent operation requires Messages or phone
proof. A process observation never proves that an agent can complete a task.
"""

from __future__ import annotations

from contextlib import contextmanager
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time
import uuid


SCHEMA = "wideband.agent-roster.v1"
MANIFEST_SCHEMA = "wideband.agent-launch.v1"
NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,31}\Z")
ROLES = {"head", "website", "research", "qa", "general"}
CAPABILITIES = {"web_search", "browser", "scripting"}
DEFAULT_CAPABILITIES = ["web_search", "browser", "scripting"]
ROOT = Path.home() / ".wideband" / "fleetdeck"
ROSTER = ROOT / "agent-roster.json"
_PROVIDER_CACHE: tuple[tuple, float, str | None] | None = None
_ROLE_BRIEFS = {
    "head": "Coordinate the owner's work and delegate only to observed, registered agents.",
    "website": "Maintain the owner's selected website project and local development workflow.",
    "research": "Research the owner's questions and record findings with primary-source citations.",
    "qa": "Verify the owner's selected work; report reproducible failures and evidence.",
    "general": "Handle the current assignment; do not infer a permanent mission from a name.",
}


class ProvisionError(ValueError):
    pass


def _stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _private_dir(path: Path) -> None:
    home = Path.home().resolve()
    if path != home and not path.is_relative_to(home):
        raise ProvisionError("private fleet directory is outside this login")
    for parent in reversed((path, *path.parents)):
        if parent == home or parent.is_relative_to(home):
            if parent.is_symlink():
                raise ProvisionError("private fleet path is a symlink")
            if parent.exists() and (not parent.is_dir() or parent.stat().st_uid != os.getuid()):
                raise ProvisionError("private fleet directory has unsafe ownership")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.stat().st_mode & 0o077:
        raise ProvisionError("private fleet directory has unsafe permissions")


def _private_json(path: Path, limit: int = 65536) -> dict | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ProvisionError("private agent data cannot be opened safely") from exc
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size > limit):
            raise ProvisionError("private agent data has unsafe ownership, permissions, or size")
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = -1
            data = json.load(stream)
        if not isinstance(data, dict):
            raise ProvisionError("private agent data is invalid")
        return data
    except (OSError, ValueError) as exc:
        raise ProvisionError("private agent data cannot be read") from exc
    finally:
        if fd >= 0:
            os.close(fd)


def _atomic(path: Path, content: str) -> None:
    _private_dir(path.parent)
    if path.is_symlink():
        raise ProvisionError("private agent file is a symlink")
    if path.exists():
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ProvisionError("private agent file has unsafe ownership or permissions")
    fd, temporary = tempfile.mkstemp(prefix=".agent-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _save_json(path: Path, data: dict) -> None:
    _atomic(path, json.dumps(data, sort_keys=True, indent=2) + "\n")


@contextmanager
def _lock():
    _private_dir(ROOT)
    try:
        fd = os.open(ROOT / "agent-roster.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        raise ProvisionError("agent roster lock cannot be opened safely") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ProvisionError("agent roster lock has unsafe ownership or permissions")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _read() -> dict:
    data = _private_json(ROSTER)
    if data is None:
        return {"schema_version": SCHEMA, "revision": 0, "agents": []}
    if (set(data) != {"schema_version", "revision", "agents"}
            or data["schema_version"] != SCHEMA or type(data["revision"]) is not int
            or data["revision"] < 0 or not isinstance(data["agents"], list)
            or len(data["agents"]) > 128):
        raise ProvisionError("fleet roster schema is invalid")
    seen = set()
    for agent in data["agents"]:
        if (not isinstance(agent, dict)
                or set(agent) != {"name", "role", "provider", "workspace", "created_at", "launch"}
                or not isinstance(agent["name"], str) or not NAME.fullmatch(agent["name"])
                or agent["name"] in seen or not isinstance(agent["role"], str)
                or agent["role"] not in ROLES or agent["provider"] != "claude"
                or not isinstance(agent["workspace"], str)
                or (agent["workspace"] and not Path(agent["workspace"]).is_relative_to(Path.home()))
                or (not agent["workspace"] and agent["role"] != "website")
                or not isinstance(agent["created_at"], str)
                or (agent["launch"] is not None and (
                    not isinstance(agent["launch"], dict)
                    or set(agent["launch"]) != {"session_id", "pane_pid"}
                    or not isinstance(agent["launch"]["session_id"], str)
                    or not re.fullmatch(r"\$\d+", agent["launch"]["session_id"])
                    or not isinstance(agent["launch"]["pane_pid"], str)
                    or not agent["launch"]["pane_pid"].isdigit()))):
            raise ProvisionError("fleet roster contains an invalid agent")
        if (agent["name"] == "wb-head") != (agent["role"] == "head"):
            raise ProvisionError("the head role owns only wb-head")
        seen.add(agent["name"])
    return data


def _save(data: dict) -> None:
    _save_json(ROSTER, data)


def _call(arguments: list[str], timeout: int = 8, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(arguments, input=input_text, capture_output=True, text=True,
                              timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProvisionError("agent runtime command could not complete") from exc


def _verified_file(variable: str, executable: bool = False) -> str | None:
    value = os.environ.get(variable, "")
    path = Path(value)
    if not value or not path.is_absolute() or path.is_symlink():
        return None
    try:
        info = path.stat()
    except OSError:
        return None
    if (not stat.S_ISREG(info.st_mode) or info.st_uid not in (os.getuid(), 0)
            or info.st_mode & 0o022 or (executable and not os.access(path, os.X_OK))):
        return None
    return str(path)


def _tmux() -> str:
    # Supplied by the installer after its checksum-backed toolchain gate.
    path = _verified_file("FLEETDECK_VERIFIED_TMUX", executable=True)
    if not path:
        raise ProvisionError("verified tmux is unavailable")
    return path


def _provider(refresh: bool = False) -> str | None:
    global _PROVIDER_CACHE
    candidates = []
    home = Path.home().resolve()
    for path in (Path.home() / ".local/bin/claude", Path.home() / "bin/claude"):
        try:
            resolved = path.resolve(strict=True)
            info = resolved.stat()
        except OSError:
            continue
        if (not resolved.is_relative_to(home) or not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid() or info.st_mode & 0o022
                or not os.access(resolved, os.X_OK)):
            continue
        candidates.append((str(resolved), info.st_ino, info.st_mtime_ns))
    key = (str(home), tuple(candidates))
    if not refresh and _PROVIDER_CACHE and _PROVIDER_CACHE[0] == key:
        if time.monotonic() - _PROVIDER_CACHE[1] < 20:
            return _PROVIDER_CACHE[2]
    selected = None
    for path, _inode, _mtime in candidates:
        try:
            result = _call([path, "auth", "status", "--json"], timeout=15)
            auth = json.loads(result.stdout) if len(result.stdout) < 65536 else {}
            if result.returncode == 0 and isinstance(auth, dict) and auth.get("loggedIn") is True:
                selected = path
                break
        except (ProvisionError, ValueError):
            continue
    _PROVIDER_CACHE = (key, time.monotonic(), selected)
    return selected


def tooling_status() -> dict:
    """Report installed files; browser and task success need separate proof."""
    node = _verified_file("FLEETDECK_VERIFIED_NODE", executable=True)
    python = _verified_file("FLEETDECK_VERIFIED_PYTHON", executable=True)
    cli = _verified_file("FLEETDECK_PLAYWRIGHT_CLI")
    module = _verified_file("WB_PLAYWRIGHT_MODULE")
    browsers = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/nonexistent"))
    chromium = False
    if browsers.is_absolute() and not browsers.is_symlink() and browsers.is_dir():
        chromium = any(path.is_file() and os.access(path, os.X_OK)
                       for pattern in ("chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
                                       "chromium-*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
                                       "chromium_headless_shell-*/chrome-headless-shell-mac-*/chrome-headless-shell",
                                       "chromium-*/chrome-linux*/chrome")
                       for path in browsers.glob(pattern))
    return {"web_search": {"state": "provider_native", "verification": "provider capability; use not tested"},
            "scripting": {"state": "installed" if node and python else "incomplete",
                          "node": node, "python": python, "verification": "installed files"},
            "browser": {"state": "installed" if node and cli and module and chromium else "not_installed",
                        "node": node, "cli": cli, "module": module,
                        "browsers": str(browsers) if chromium else None,
                        "verification": "pinned installed files; browser launch not tested"}}


def _workspace(value: str, name: str, role: str, create: bool = False) -> Path:
    if not isinstance(value, str) or len(value) > 400 or any(ord(c) < 32 for c in value):
        raise ProvisionError("workspace is invalid")
    if role == "website" and not value:
        raise ProvisionError("website agent needs the actual existing project path")
    default = Path.home() / "wideband" / ("head" if role == "head" else f"agents/{name}")
    path = Path(value).expanduser() if value else default
    home = Path.home().resolve()
    if not path.is_absolute():
        raise ProvisionError("workspace must be a real absolute directory")
    for parent in (path, *path.parents):
        if (parent == Path.home() or parent.is_relative_to(Path.home())) and parent.is_symlink():
            raise ProvisionError("workspace must not traverse a symlink")
    canonical = path.resolve(strict=False)
    if (canonical == home or not canonical.is_relative_to(home)
            or any(part in {".ssh", ".wideband", ".config", ".claude", ".codex", "Library"}
                   for part in canonical.relative_to(home).parts)):
        raise ProvisionError("workspace must be an ordinary directory under this login")
    if value and not canonical.is_dir() and not (role != "website" and canonical == default.resolve()):
        raise ProvisionError("the selected project directory does not exist")
    for parent in (canonical, *canonical.parents):
        if parent == home or parent.is_relative_to(home):
            if parent.exists() and (not parent.is_dir() or parent.stat().st_uid != os.getuid()
                                    or parent.stat().st_mode & 0o022):
                raise ProvisionError("workspace is not an owned, privately writable directory")
    if create and not canonical.exists():
        canonical.mkdir(parents=True, mode=0o700)
    return canonical


def list_workspaces() -> list[dict]:
    """Bounded project choices, excluding hidden and system directories."""
    found = {}
    for root in (Path.home() / name for name in ("srv", "Projects", "projects", "wideband")):
        if root.is_symlink() or not root.is_dir():
            continue
        try:
            candidates = sorted(root.iterdir(), key=lambda path: path.name)[:128]
        except OSError:
            continue
        for candidate in candidates:
            if candidate.name.startswith(".") or candidate.name in {"agents", "head", "node_modules", "vendor"}:
                continue
            try:
                path = _workspace(str(candidate), "project", "website")
            except (ProvisionError, OSError):
                continue
            found[str(path)] = {"path": str(path), "label": candidate.name}
            if len(found) >= 128:
                return list(found.values())
    return list(found.values())


def _agent_root(name: str) -> Path:
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ProvisionError("invalid agent name")
    return ROOT / "agents" / name


def _manifest(agent: dict) -> dict | None:
    data = _private_json(_agent_root(agent["name"]) / "manifest.json")
    if data is None:
        return None
    if (data.get("schema_version") != MANIFEST_SCHEMA or data.get("name") != agent["name"]
            or data.get("workspace") != agent["workspace"] or data.get("role") != agent["role"]
            or data.get("provider") != agent["provider"]
            or not isinstance(data.get("capabilities"), list)
            or any(not isinstance(item, str) or item not in CAPABILITIES for item in data["capabilities"])
            or not isinstance(data.get("files"), dict)
            or not isinstance(data.get("claude_session_id"), str)
            or (data.get("launch") is not None and (
                not isinstance(data["launch"], dict)
                or not isinstance(data["launch"].get("launch_id"), str)
                or not isinstance(data["launch"].get("executable"), str)
                or not Path(data["launch"]["executable"]).is_absolute()))):
        raise ProvisionError("private agent manifest does not match its roster")
    try:
        uuid.UUID(data["claude_session_id"])
    except ValueError as exc:
        raise ProvisionError("private agent session identity is invalid") from exc
    return data


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _onboarding_context() -> str:
    """Copy only bounded display labels and recipe, never private setup answers."""
    try:
        saved = _private_json(Path.home() / ".wideband/setup/state.json", limit=2 * 1024 * 1024)
    except ProvisionError:
        return ""
    metadata = saved.get("metadata") if saved else None
    if not isinstance(metadata, dict):
        return ""
    context = []
    for key, label in (("os_name", "OS display name"), ("agent_name", "Head display name")):
        value = metadata.get(key)
        if isinstance(value, str) and re.fullmatch(r"[\w][\w .'-]{0,59}", value, flags=re.UNICODE):
            context.append(f"{label}: {value}")
    recipe = metadata.get("first_goal")
    if isinstance(recipe, str) and recipe in {"research", "website", "proposal"}:
        context.append(f"Owner-selected first recipe: {recipe}")
        context.append(f"Read the staged brief at {Path.home() / 'wideband/first-project/FIRST-GOAL.md'} if present.")
    if not context:
        return ""
    return "\nSaved onboarding context:\n" + "\n".join(context) + (
        "\nThese are owner-selected labels and project context. Await an explicit assignment;\n"
        "a saved recipe and restored scrollback do not authorize new external actions.\n")


def _managed_file(folder: Path, name: str, content: str, manifest: dict) -> None:
    path = folder / name
    if path.exists() or path.is_symlink():
        if path.is_symlink():
            raise ProvisionError("managed agent instructions are a symlink")
        info = path.stat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size > 65536):
            raise ProvisionError("managed agent instructions are unsafe")
        current = path.read_text(encoding="utf-8")
        if current == content:
            manifest["files"][name] = _digest(content)
            return
        if manifest["files"].get(name) != _digest(current):
            raise ProvisionError("agent instructions were customized; review before replacing the managed template")
    _atomic(path, content)
    manifest["files"][name] = _digest(content)


def _prepare(agent: dict, capabilities: list[str] | None = None,
             transport_instructions: str | None = None) -> dict:
    folder = _agent_root(agent["name"])
    _private_dir(folder)
    manifest = _manifest(agent) or {
        "schema_version": MANIFEST_SCHEMA, "name": agent["name"], "role": agent["role"],
        "provider": agent["provider"], "workspace": agent["workspace"],
        "created_at": agent["created_at"],
        "capabilities": DEFAULT_CAPABILITIES.copy() if capabilities is None else capabilities,
        "claude_session_id": str(uuid.uuid4()), "files": {}, "transport_instructions": None, "launch": None}
    if capabilities is not None and manifest["capabilities"] != capabilities:
        raise ProvisionError("agent capabilities differ from its existing template; operator review required")
    if transport_instructions is not None:
        transport = Path(transport_instructions)
        if (not transport.is_absolute() or transport.is_symlink() or not transport.is_file()
                or transport.stat().st_uid != os.getuid() or transport.stat().st_mode & 0o077
                or not transport.resolve().is_relative_to(Path.home().resolve())):
            raise ProvisionError("head transport instructions must be an owned private file")
        manifest["transport_instructions"] = str(transport)
    requested = ", ".join(manifest["capabilities"]) or "none"
    identity = (f"# Wideband agent: {agent['name']}\n\n"
                f"Role: {agent['role']}\nProvider: {agent['provider']}\n"
                f"Workspace: {agent['workspace']}\n\n{_ROLE_BRIEFS[agent['role']]}\n\n"
                f"Requested tools: {requested}. Read tools.json for installation evidence.\n"
                "Work comes from the owner or an explicit head-agent handoff.\n"
                "A terminal name and restored scrollback grant no new authorization.\n"
                "Record progress in state.md without secrets or raw owner messages.\n")
    instructions = (
        "# Wideband standard agent template\n\n"
        f"Read {folder / 'identity.md'} and {folder / 'state.md'} when starting or recovering.\n"
        f"Work in {agent['workspace']}; {_ROLE_BRIEFS[agent['role']]}\n"
        "Read the project's existing AGENTS.md and CLAUDE.md. Wideband does not replace them.\n"
        f"Read {folder / 'tools.json'} for exact installed paths and requested capabilities.\n\n"
        "Use only the capabilities requested in tools.json; ask before expanding this template.\n"
        "Use the provider's native web search when requested and available; cite sources.\n"
        "Use the listed private Python and Node runtimes for project-scoped scripts.\n"
        "For browser work, use the pinned Playwright module with an isolated Chromium context.\n"
        "In a Node script, require(process.env.WB_PLAYWRIGHT_MODULE); launch chromium,\n"
        "create a newContext(), then use page.goto(), page.getByRole().click(), and assertions.\n"
        "PLAYWRIGHT_BROWSERS_PATH points to the packaged browsers. Do not use npx downloads.\n"
        "Installed files do not prove a browser launched or a page flow passed.\n"
        "Playwright controls browser pages; Mac desktop access needs separate owner grants.\n\n"
        "Preserve client work. The workspace boundary is an instruction, not OS filesystem isolation.\n"
        "Do not inspect other agents' private credentials or configuration. Keep secrets out of memory.\n"
        "Obtain owner authorization before external messages, publication, financial actions, or destructive changes.\n"
        "Do not claim website connections, iMessage binding, provider sign-in, or task success without evidence.\n"
        "An observed provider process proves only the current launch; report blocked human steps plainly.\n")
    if agent["role"] == "head":
        instructions += _onboarding_context()
        instructions += (
            "\nOnly this registered wb-head may receive the separately bound owner iMessage chat.\n"
            "Do not choose recipients or call imsg send directly. Use the guarded outbox described\n"
            "in the transport sidecar when present; local agent creation does not activate Messages.\n")
        if manifest.get("transport_instructions"):
            instructions += f"Read transport instructions at {manifest['transport_instructions']} before replying.\n"
        instructions += (
            "\nFor internal routing, list agents using the fixed fleet command:\n"
            '  "$FLEETDECK_VERIFIED_PYTHON" "$WB_AGENT_COMMAND" list\n'
            "Delegate only to a target whose current state is process_observed.\n"
            "Write the bounded task to a private task file, then submit it via stdin, for example:\n"
            '  "$FLEETDECK_VERIFIED_PYTHON" "$WB_AGENT_COMMAND" delegate research < task.txt\n'
            "The result 'submitted' means terminal input was submitted, not read or completed.\n"
            "Do not automatically repeat an uncertain submission. Read the child's state.md\n"
            "under the private fleet agent folder for its progress, evidence, and result.\n")
    _managed_file(folder, "identity.md", identity, manifest)
    _managed_file(folder, "instructions.md", instructions, manifest)
    state_path = folder / "state.md"
    if state_path.is_symlink():
        raise ProvisionError("agent state is a symlink")
    if state_path.exists() and (not state_path.is_file() or state_path.stat().st_uid != os.getuid()
                                or state_path.stat().st_mode & 0o077):
        raise ProvisionError("agent state has unsafe ownership or permissions")
    if not state_path.exists():
        _atomic(folder / "state.md", "# Current assignment\n\nNo task has been assigned.\n"
                "Record verified progress, blockers, and the next safe action here.\n")
    _save_json(folder / "tools.json", {"requested": manifest["capabilities"], "installation": tooling_status()})
    _save_json(folder / "manifest.json", manifest)
    return manifest


def _pane_details(name: str) -> dict | None:
    result = _call([_tmux(), "list-panes", "-s", "-t", f"={name}", "-F",
                    "#{session_id}\t#{pane_id}\t#{pane_pid}\t#{pane_current_command}\t#{pane_current_path}\t#{pane_dead}"])
    if result.returncode != 0:
        error = result.stderr.strip()
        if (error.startswith(("can't find session:", "can't find window:", "no server running on "))
                or (error.startswith("error connecting to ") and error.endswith("(No such file or directory)"))):
            return None
        raise ProvisionError("tmux status could not be checked")
    lines = result.stdout.splitlines()
    if len(lines) != 1:
        raise ProvisionError("agent session has an ambiguous pane layout")
    fields = lines[0].split("\t")
    if (len(fields) != 6 or not re.fullmatch(r"\$\d+", fields[0])
            or not re.fullmatch(r"%\d+", fields[1]) or not fields[2].isdigit()):
        raise ProvisionError("agent pane identity could not be checked")
    return dict(zip(("session_id", "pane_id", "pane_pid", "command", "workspace", "dead"), fields))


def _pane(name: str) -> tuple[bool, str | None]:
    pane = _pane_details(name)
    return bool(pane), pane["command"] if pane else None


def _launch_identity(name: str) -> dict | None:
    pane = _pane_details(name)
    return {key: pane[key] for key in ("session_id", "pane_pid")} if pane else None


def _process(pane: dict, executable: str) -> dict | None:
    if pane["dead"] == "1":
        return None
    result = _call(["/bin/ps", "-p", pane["pane_pid"], "-o", "uid=,lstart=,comm="])
    match = re.fullmatch(r"\s*(\d+)\s+([A-Za-z]{3}\s+[A-Za-z]{3}\s+\d+\s+\d{2}:\d{2}:\d{2}\s+\d{4})\s+(.+?)\s*",
                         result.stdout)
    if result.returncode or not match or int(match[1]) != os.getuid():
        return None
    command = match[3]
    expected = Path(executable)
    # Direct native-provider launch, not a shell or generic node process.
    if command not in (str(expected), expected.name, "claude"):
        return None
    if pane["command"] not in {expected.name, "claude"}:
        return None
    return {"started": " ".join(match[2].split()), "command": command, "uid": os.getuid()}


def _owned_launch(agent: dict, manifest: dict | None, pane: dict | None) -> bool:
    receipt = manifest.get("launch") if manifest else None
    if not isinstance(receipt, dict) or not pane or not agent["workspace"]:
        return False
    if (agent["launch"] != {key: pane[key] for key in ("session_id", "pane_pid")}
            or receipt.get("pane_id") != pane["pane_id"]
            or not isinstance(receipt.get("executable"), str)
            or Path(pane["workspace"]).resolve() != Path(agent["workspace"]).resolve()):
        return False
    process = _process(pane, receipt["executable"])
    return bool(process and process == receipt.get("process"))


def _transcript_exists(agent: dict, manifest: dict) -> bool:
    project = re.sub(r"[^A-Za-z0-9-]", "-", str(Path(agent["workspace"]).resolve()))
    folder = Path.home() / ".claude" / "projects" / project
    path = folder / (manifest["claude_session_id"] + ".jsonl")
    if folder.is_symlink() or path.is_symlink():
        return False
    try:
        info = path.stat()
        return stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_size > 0
    except OSError:
        return False


def _status(agent: dict, provider_ready: bool | None = None) -> dict:
    pane = _pane_details(agent["name"])
    manifest = _manifest(agent)
    observed = _owned_launch(agent, manifest, pane)
    if provider_ready is None:
        provider_ready = _provider() is not None
    state = ("process_observed" if observed else "session_unverified" if pane else
             "awaiting_project" if not agent["workspace"] else "planned")
    action = {"process_observed": "open_terminal", "session_unverified": "operator_review",
              "awaiting_project": "choose_project", "planned": "activate" if provider_ready else "sign_in"}[state]
    message = {
        "process_observed": "Provider process observed in this agent's workspace.",
        "session_unverified": "Existing session is not an observed launch of this agent; review it before repair.",
        "awaiting_project": "Choose the actual existing website project.",
        "planned": "Ready to activate." if provider_ready else "Sign in to Claude in Wideband Setup, then activate."}[state]
    if pane and not observed and manifest and isinstance(manifest.get("launch"), dict):
        receipt = manifest["launch"]
        interrupted = (not receipt.get("process") or (
            receipt.get("pane_id") == pane["pane_id"]
            and _process(pane, receipt["executable"]) == receipt.get("process")))
        if interrupted:
            marker = _call([_tmux(), "show-environment", "-t", f"={agent['name']}", "WB_AGENT_LAUNCH_ID"])
            if marker.returncode == 0 and marker.stdout.strip() == "WB_AGENT_LAUNCH_ID=" + manifest["launch"].get("launch_id", ""):
                state, action = "launch_pending", "activate"
                message = "Launch requested; retry activation to reconcile its process receipt."
    return {"name": agent["name"], "role": agent["role"], "provider": agent["provider"],
            "workspace": agent["workspace"], "state": state,
            "pane_command": pane["command"] if observed else None,
            "pane_id": pane["pane_id"] if observed else None,
            "provider_ready": provider_ready, "next_action": action, "message": message,
            "capabilities": manifest["capabilities"] if manifest else DEFAULT_CAPABILITIES.copy(),
            "tools": tooling_status(),
            "template": str(_agent_root(agent["name"]) / "instructions.md") if manifest else None,
            "resume_available": _transcript_exists(agent, manifest) if manifest else False}


def list_agents(check_provider: bool = True) -> list[dict]:
    # Snapshot collectors have their own short deadline. Process receipts do
    # not depend on an auth-status probe; allow metadata-only collection.
    ready = _provider() is not None if check_provider else False
    agents = [_status(agent, ready) for agent in _read()["agents"]]
    if not check_provider:
        for agent in agents:
            agent["provider_ready"] = None
            agent["provider_status"] = "not_checked"
            if agent["state"] == "planned":
                agent["next_action"] = "activate"
                agent["message"] = "Activate to check provider sign-in and start this agent."
    return agents


def seed_default_roster() -> None:
    """Declare the starter team without starting providers or modifying projects."""
    with _lock():
        data = _read()
        known = {item["name"] for item in data["agents"]}
        changed = not ROSTER.exists()
        for name, role in (("wb-head", "head"), ("website", "website"), ("research", "research"), ("qa", "qa")):
            if name in known:
                continue
            data["agents"].append({"name": name, "role": role, "provider": "claude",
                                   "workspace": "" if role == "website" else str(Path.home() / "wideband" /
                                       ("head" if role == "head" else f"agents/{name}")),
                                   "created_at": _stamp(), "launch": None})
            data["revision"] += 1
            changed = True
        if changed:
            _save(data)


def create_agent(payload: dict) -> dict:
    required = {"name", "role", "workspace"}
    allowed = required | {"provider", "capabilities", "activate"}
    if not isinstance(payload, dict) or not required <= set(payload) or set(payload) - allowed:
        raise ProvisionError("expected name, role, workspace, and optional provider, capabilities, activate")
    name, role, supplied = payload["name"], payload["role"], payload["workspace"]
    if (not isinstance(name, str) or not NAME.fullmatch(name)
            or not isinstance(role, str) or role not in ROLES):
        raise ProvisionError("agent name or role is invalid")
    if (name == "wb-head") != (role == "head"):
        raise ProvisionError("the head role owns only wb-head")
    if payload.get("provider", "claude") != "claude":
        raise ProvisionError("only Claude has a supported customer activation adapter")
    activate = payload.get("activate", True)
    if type(activate) is not bool:
        raise ProvisionError("activate must be a boolean")
    capabilities = payload.get("capabilities")
    if "capabilities" in payload and capabilities is None:
        raise ProvisionError("agent capabilities must be a list")
    if capabilities is not None and (not isinstance(capabilities, list) or len(capabilities) > len(CAPABILITIES)
            or any(not isinstance(capability, str) or capability not in CAPABILITIES for capability in capabilities)
            or len(set(capabilities)) != len(capabilities)):
        raise ProvisionError("agent capabilities are invalid")
    if capabilities is not None:
        capabilities = [capability for capability in DEFAULT_CAPABILITIES if capability in capabilities]
    canonical = _workspace(supplied, name, role)
    with _lock():
        data = _read()
        item = next((agent for agent in data["agents"] if agent["name"] == name), None)
        if item is not None:
            if item["role"] != role or (item["workspace"] and item["workspace"] != str(canonical)):
                raise ProvisionError("agent name already owns a different role or workspace")
            if not item["workspace"]:
                if _pane_details(name):
                    raise ProvisionError("an unregistered tmux session already uses this name")
                item["workspace"] = str(canonical)
                data["revision"] += 1
                _save(data)
        else:
            if len(data["agents"]) >= 128:
                raise ProvisionError("customer roster is full")
            if _pane_details(name):
                raise ProvisionError("an unregistered tmux session already uses this name")
            _workspace(supplied, name, role, create=True)
            item = {"name": name, "role": role, "provider": "claude", "workspace": str(canonical),
                    "created_at": _stamp(), "launch": None}
            data["agents"].append(item)
            data["revision"] += 1
            _save(data)
        _workspace(item["workspace"], name, role, create=True)
        _prepare(item, capabilities)
        if activate:
            return _activate(data, item)
        return _status(item)


def _record_launch(data: dict, item: dict, manifest: dict, pane: dict) -> bool:
    intent = manifest.get("launch")
    if not isinstance(intent, dict) or not isinstance(intent.get("launch_id"), str):
        return False
    marker = _call([_tmux(), "show-environment", "-t", f"={item['name']}", "WB_AGENT_LAUNCH_ID"])
    if marker.returncode or marker.stdout.strip() != "WB_AGENT_LAUNCH_ID=" + intent["launch_id"]:
        return False
    if Path(pane["workspace"]).resolve() != Path(item["workspace"]).resolve():
        return False
    process = _process(pane, intent["executable"])
    if not process:
        return False
    if intent.get("process") and (intent["process"] != process or intent.get("pane_id") != pane["pane_id"]):
        return False
    intent.update({"pane_id": pane["pane_id"], "process": process, "observed_at": _stamp()})
    item["launch"] = {key: pane[key] for key in ("session_id", "pane_pid")}
    _save_json(_agent_root(item["name"]) / "manifest.json", manifest)
    data["revision"] += 1
    _save(data)
    return True


def _activate(data: dict, item: dict, transport_instructions: str | None = None) -> dict:
    if not item["workspace"]:
        raise ProvisionError("choose the actual website project before activation")
    _workspace(item["workspace"], item["name"], item["role"], create=True)
    manifest = _prepare(item, transport_instructions=transport_instructions)
    pane = _pane_details(item["name"])
    if pane:
        if _owned_launch(item, manifest, pane):
            return _status(item)
        receipt = manifest.get("launch")
        if isinstance(receipt, dict) and _record_launch(data, item, manifest, pane):
            return _status(item)
        raise ProvisionError("existing session is not this agent launch; operator review required")
    cli = _provider(refresh=True)
    if cli is None:
        status = _status(item, False)
        status.update(state="awaiting_sign_in", next_action="sign_in")
        return status
    folder = _agent_root(item["name"])
    resume = _transcript_exists(item, manifest)
    arguments = [cli, "--resume" if resume else "--session-id", manifest["claude_session_id"],
                 "--append-system-prompt-file", str(folder / "instructions.md")]
    launch_id = str(uuid.uuid4())
    manifest["launch"] = {"launch_id": launch_id, "executable": cli,
                          "requested_at": _stamp(), "resume": resume, "process": None}
    # The marker lets a retry reconcile only this interrupted launch.
    _save_json(folder / "manifest.json", manifest)
    environment = []
    for variable in ("FLEETDECK_VERIFIED_NODE", "FLEETDECK_VERIFIED_PYTHON",
                     "FLEETDECK_PLAYWRIGHT_CLI", "WB_PLAYWRIGHT_MODULE", "NODE_PATH",
                     "PLAYWRIGHT_BROWSERS_PATH", "WB_AGENT_COMMAND", "PATH"):
        value = os.environ.get(variable)
        if value is not None:
            environment.extend(["-e", variable + "=" + value])
    result = _call([_tmux(), "new-session", "-d", "-s", item["name"], "-c", item["workspace"],
                    "-e", "WB_AGENT_LAUNCH_ID=" + launch_id,
                    "-e", "WB_SESSION_IDENTITY=" + str(folder / "identity.md"),
                    "-e", "WB_AGENT_STATE=" + str(folder / "state.md"), *environment, *arguments], timeout=10)
    if result.returncode:
        raise ProvisionError("tmux could not launch the agent; its saved template is ready for retry")
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        pane = _pane_details(item["name"])
        if pane and _record_launch(data, item, manifest, pane):
            return _status(item, True)
        if pane is None:
            raise ProvisionError("provider exited during startup; inspect sign-in and project trust in Wideband Setup")
        time.sleep(0.15)
    status = _status(item, True)
    status.update(state="launch_pending", next_action="activate",
                  message="Launch requested; provider process has not been observed yet. Retry activation to reconcile it.")
    return status


def activate_agent(name: str) -> dict:
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ProvisionError("invalid agent name")
    with _lock():
        data = _read()
        item = next((agent for agent in data["agents"] if agent["name"] == name), None)
        if item is None:
            raise ProvisionError("agent is not registered")
        return _activate(data, item)


def head_workspace() -> str | None:
    """Let first Messages binding adopt an already registered head workspace."""
    item = next((agent for agent in _read()["agents"] if agent["name"] == "wb-head"), None)
    if item is None:
        return None
    return str(_workspace(item["workspace"], "wb-head", "head"))


def ensure_head_agent(workspace: str, transport_instructions: str | None = None) -> dict:
    """Shared wb-head owner for Setup and the separately bound Messages keeper."""
    create_agent({"name": "wb-head", "role": "head", "workspace": workspace, "activate": False})
    with _lock():
        data = _read()
        item = next(agent for agent in data["agents"] if agent["name"] == "wb-head")
        return _activate(data, item, transport_instructions)


def resume_agents() -> list[dict]:
    """One-shot login recovery of explicitly launched agents, never planned entries.

    No existing session is restarted or replaced. A deliberate exit stays stopped
    until the next GUI login or an explicit Activate click, without a keep loop.
    """
    results = []
    with _lock():
        data = _read()
        for item in data["agents"]:
            manifest = _manifest(item)
            receipt = manifest.get("launch") if manifest else None
            if not isinstance(receipt, dict) or not receipt.get("process"):
                continue
            try:
                if _pane_details(item["name"]) is not None:
                    results.append(_status(item))
                    continue
                results.append(_activate(data, item))
            except (ProvisionError, OSError) as exc:
                results.append({"name": item["name"], "state": "resume_blocked",
                                "next_action": "operator_review", "message": str(exc)})
    return results


def delegate_task(name: str, text: str) -> dict:
    """Submit bounded literal input to an observed launch, never to a shell.

    A receipt attests only that input was submitted. Reading/completion requires
    the child's explicit result. Uncertain submission is held for review.
    """
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ProvisionError("invalid agent name")
    if (not isinstance(text, str) or not text.strip() or len(text) > 12000
            or len(text.encode("utf-8")) > 48000
            or any((ord(char) < 32 and char not in "\r\n\t") or ord(char) == 127 for char in text)):
        raise ProvisionError("task text is empty, too long, or contains terminal control characters")
    # One literal line plus one deliberate Enter; no terminal escape sequences.
    task = " ".join(text.split())
    with _lock():
        data = _read()
        item = next((agent for agent in data["agents"] if agent["name"] == name), None)
        if item is None:
            raise ProvisionError("target agent is not registered")
        manifest = _manifest(item)
        pane = _pane_details(name)
        if not _owned_launch(item, manifest, pane):
            raise ProvisionError("target is not an observed agent launch; no task was submitted")
        task_id = str(uuid.uuid4())
        receipt = {"task_id": task_id, "target": name, "created_at": _stamp(),
                   "task_sha256": _digest(task), "pane_id": pane["pane_id"], "state": "prepared"}
        receipt_path = _agent_root(name) / "delegations" / (task_id + ".json")
        _save_json(receipt_path, receipt)
        buffer = "wb-agent-" + task_id
        paste_started = False
        try:
            loaded = _call([_tmux(), "load-buffer", "-b", buffer, "-"], input_text=task)
            if loaded.returncode:
                raise ProvisionError("task buffer could not be prepared")
            current = _pane_details(name)
            if current != pane or not _owned_launch(item, manifest, current):
                raise ProvisionError("target changed before submission; no task was submitted")
            paste_started = True
            pasted = _call([_tmux(), "paste-buffer", "-p", "-b", buffer, "-t", pane["pane_id"]])
            if pasted.returncode:
                raise ProvisionError("task submission is uncertain; inspect the target before retry")
            current = _pane_details(name)
            if current != pane or not _owned_launch(item, manifest, current):
                raise ProvisionError("target changed after paste; inspect it before any retry")
            submitted = _call([_tmux(), "send-keys", "-t", pane["pane_id"], "Enter"])
            if submitted.returncode:
                raise ProvisionError("task submission is uncertain; inspect the target before retry")
            receipt.update(state="submitted", submitted_at=_stamp())
            _save_json(receipt_path, receipt)
            return {**receipt, "next_action": "read_agent_result",
                    "message": "Task input submitted; agent acceptance and completion are not yet confirmed.",
                    "state_file": str(_agent_root(name) / "state.md")}
        except (ProvisionError, OSError):
            receipt.update(state="held_for_review" if paste_started else "not_submitted", updated_at=_stamp())
            _save_json(receipt_path, receipt)
            raise
        finally:
            try:
                _call([_tmux(), "delete-buffer", "-b", buffer])
            except ProvisionError:
                pass
