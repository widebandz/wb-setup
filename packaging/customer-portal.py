#!/usr/bin/env python3
"""Fleetdeck customer portal: phone home, read-only head view, and beta notes.

This standalone server is copied into the customer Fleetdeck bundle as
portal_server.py. It deliberately has no import path to the operator portal,
chat, ttyd, adopt, or machine-control code.
"""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hmac
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import threading
from urllib.parse import urlsplit
import urllib.error
import urllib.request
import uuid


HERE = Path(__file__).resolve().parent
CFG_FILE = HERE / "config.json"
REGISTRY = HERE / "services.json"
SETUP_STATE = Path(os.environ.get("FLEETDECK_SETUP_STATE_PATH", "~/.wideband/setup/state.json")).expanduser()
GOAL_STATUS = Path(os.environ.get("FLEETDECK_FIRST_GOAL_STATUS_PATH", "~/.wideband/first-goal/status.json")).expanduser()
NOTES_PATH = Path(os.environ.get("FLEETDECK_NOTES_PATH", "~/.wideband/fleetdeck/notes-beta.json")).expanduser()
ACCESS_TOKEN_PATH = Path(os.environ.get(
    "FLEETDECK_ACCESS_TOKEN_PATH", "~/.wideband/fleetdeck/phone-access-token")).expanduser()
NOTE_MAX = 500
BODY_MAX = 64 * 1024
NOTES_FILE_MAX = 32 * 1024 * 1024  # 500 notes × 12k Unicode characters
_notes_thread_lock = threading.Lock()


def access_token() -> str | None:
    """Read one owner-only 256-bit capability without following a symlink."""
    try:
        fd = os.open(ACCESS_TOKEN_PATH, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o777 != 0o600 or info.st_size > 65):
                return None
            raw = stream.read(66)
        value = raw.removesuffix(b"\n").decode("ascii")
        return value if re.fullmatch(r"[0-9a-f]{64}", value) else None
    except (OSError, UnicodeError):
        return None


def capability_route(path: str) -> tuple[str, str] | None:
    """Return (customer route, URL prefix) only for the exact live capability."""
    match = re.fullmatch(r"/p/([0-9a-f]{64})(/.*)?", path)
    expected = access_token()
    if not match or expected is None or not hmac.compare_digest(match.group(1), expected):
        return None
    return match.group(2) or "/", "/p/" + expected


def private_json(path: Path, max_size: int = 64 * 1024) -> dict | None:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_size > max_size):
                return None
            value = json.load(stream)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, UnicodeError):
        return None


def config() -> dict:
    try:
        value = json.loads(CFG_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def phone_url(value: object) -> str:
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        return ""
    try:
        parsed = urlsplit(value)
        if (parsed.scheme == "https" and parsed.hostname and not parsed.username
                and not parsed.password and not parsed.fragment):
            return value
    except ValueError:
        pass
    return ""


def onboarding_config() -> dict | None:
    settings = config()
    if "onboarding" in settings:
        raw = settings["onboarding"]
    else:
        state = private_json(SETUP_STATE) or {}
        raw = state.get("metadata")
    if not isinstance(raw, dict):
        return None
    names = (raw.get("os_name"), raw.get("agent_name"))
    if any(not isinstance(value, str) or not value.strip() or len(value) > 64 for value in names):
        return None
    goal = raw.get("first_goal")
    if goal not in ("research", "website", "proposal"):
        return None
    return {"os_name": names[0].strip(), "agent_name": names[1].strip(),
            "first_goal": goal, "head_session": "wb-head",
            "first_project_url": phone_url(raw.get("first_project_url"))}


def active_head_pane(session: str) -> str | None:
    """Find the active Claude pane, checking both tmux and its live process."""
    if session != "wb-head":
        return None
    try:
        fields = ("#{session_name}", "#{window_active}", "#{pane_active}", "#{pane_id}",
                  "#{pane_current_command}", "#{pane_start_command}",
                  "#{pane_pid}", "#{pane_dead}")
        listed = subprocess.run(
            ["tmux", "list-panes", "-s", "-t", session,
             "-F", "|".join(fields)],
            capture_output=True, text=True, timeout=3)
        if listed.returncode:
            return None
        for line in listed.stdout.splitlines():
            parts = line.split("|")
            if len(parts) != 8 or parts[:3] != [session, "1", "1"]:
                continue
            _, _, _, pane, current, start, pid, dead = parts
            current = current.lower()
            supported_command = (
                current in {"claude", "node"}
                or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", current) is not None)
            if (not re.fullmatch(r"%[0-9]+", pane)
                    or Path(start).name != "claude"
                    or not supported_command
                    or not re.fullmatch(r"[1-9][0-9]*", pid)
                    or dead != "0"):
                return None
            process = subprocess.run(
                ["ps", "-p", pid, "-o", "args="],
                capture_output=True, text=True, timeout=3)
            argv = process.stdout.strip()
            if process.returncode or (argv != start and not argv.startswith(start + " ")):
                return None
            return pane
    except (OSError, subprocess.TimeoutExpired):
        return None
    return None


def head_session_snapshot(session: str) -> str | None:
    """Capture only a verified Claude pane, with no input channel."""
    pane = active_head_pane(session)
    if pane is None:
        return None
    try:
        captured = subprocess.run(["tmux", "capture-pane", "-p", "-t", pane,
                                   "-S", "-120"], capture_output=True, text=True, timeout=3)
        if captured.returncode or active_head_pane(session) != pane:
            return None
        return captured.stdout[-32768:]
    except (OSError, subprocess.TimeoutExpired):
        return None


def head_session_present(session: str) -> bool:
    """Report ready only while the dedicated Claude process owns the pane."""
    return active_head_pane(session) is not None


def goal_status(info: dict) -> dict:
    value = private_json(GOAL_STATUS) or {}
    if (value.get("goal") != info["first_goal"]
            or value.get("os_name") != info["os_name"]
            or value.get("agent_name") != info["agent_name"]):
        return {}
    return value


def registered_project(port: int) -> bool:
    try:
        raw = json.loads(REGISTRY.read_text(encoding="utf-8"))
        services = raw.get("services", [])
        return any(isinstance(item, dict) and item.get("id") == "first-project"
                   and item.get("source") == "wideband-first-goal"
                   and item.get("port") == port for item in services)
    except (OSError, ValueError, TypeError):
        return False


def local_project_healthy(port: int) -> bool:
    if not isinstance(port, int) or not 1024 <= port <= 65535:
        return False
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
            if response.status != 200 or json.load(response).get("service") != "wideband-first-project":
                return False
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
            return (response.status == 200
                    and response.url == f"http://127.0.0.1:{port}/"
                    and response.headers.get_content_type() == "text/html"
                    and bool(response.read(1)))
    except urllib.error.HTTPError as error:
        error.close()
        return False
    except (OSError, ValueError, urllib.error.URLError):
        return False


def live_serve_url(port: int) -> str:
    """Resolve only an HTTPS Serve mapping to the exact local project port."""
    candidates = ("/Applications/Tailscale.app/Contents/MacOS/Tailscale",
                  str(Path.home() / "Applications/Tailscale.app/Contents/MacOS/Tailscale"),
                  "/opt/homebrew/bin/tailscale")
    binary = next((path for path in candidates if os.access(path, os.X_OK)), None)
    if not binary:
        return ""
    try:
        result = subprocess.run([binary, "serve", "status", "--json"],
                                capture_output=True, text=True, timeout=3,
                                env={**os.environ, "TAILSCALE_BE_CLI": "1"})
        if result.returncode:
            return ""
        value = json.loads(result.stdout)
        tcp, web, funnel = (value.get("TCP") or {}, value.get("Web") or {},
                            value.get("AllowFunnel") or {})
        status = subprocess.run([binary, "status", "--json"], capture_output=True,
                                text=True, timeout=3,
                                env={**os.environ, "TAILSCALE_BE_CLI": "1"})
        if status.returncode:
            return ""
        dns = ((json.loads(status.stdout).get("Self") or {}).get("DNSName") or "").lower().rstrip(".")
        if not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+\.ts\.net", dns):
            return ""
        if not isinstance(tcp, dict) or not isinstance(web, dict) or not isinstance(funnel, dict):
            return ""
        for hostport, setting in web.items():
            if not isinstance(hostport, str) or not isinstance(setting, dict):
                continue
            host, separator, public_port = hostport.rpartition(":")
            if (not separator or host.lower() != dns or funnel.get(hostport) is True
                    or not public_port.isdecimal() or not 1 <= int(public_port) <= 65535
                    or not isinstance(tcp.get(public_port), dict)
                    or tcp[public_port].get("HTTPS") is not True):
                continue
            for path, handler in (setting.get("Handlers") or {}).items():
                if (isinstance(handler, dict)
                        and (handler.get("Proxy") or "").rstrip("/") == f"http://127.0.0.1:{port}"):
                    suffix = "" if public_port == "443" else f":{public_port}"
                    return phone_url(f"https://{dns}{suffix}{'' if path == '/' else path}")
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        pass
    return ""


def project_link(info: dict) -> tuple[str, bool]:
    """A phone link needs matching identity, registry, and a live local site."""
    if info["first_goal"] != "website":
        return "", False
    status = goal_status(info)
    port = status.get("port")
    if (status.get("status") != "ready" or not isinstance(port, int)
            or not registered_project(port) or not local_project_healthy(port)):
        return "", False
    # runner.py records phone_url only after it probes the HTTPS page and
    # health route. A current private Serve route must still match that proof.
    verified = phone_url(status.get("phone_url"))
    live = live_serve_url(port)
    return (live if verified and live and live.rstrip("/") == verified.rstrip("/")
            else ""), True


@contextmanager
def notes_lock():
    with _notes_thread_lock:
        if NOTES_PATH.parent.is_symlink():
            raise ValueError("notes directory is a symlink")
        NOTES_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(NOTES_PATH.parent, 0o700)
        lock = NOTES_PATH.with_name(NOTES_PATH.name + ".lock")
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError("notes lock has unsafe ownership or permissions")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def read_notes() -> list[dict]:
    if not NOTES_PATH.exists():
        return []
    value = private_json(NOTES_PATH, NOTES_FILE_MAX)
    if not isinstance(value, dict) or not isinstance(value.get("notes"), list):
        raise ValueError("notes store is unreadable or has unsafe permissions")
    return value["notes"][:NOTE_MAX]


def write_notes(items: list[dict]) -> None:
    fd, temp = tempfile.mkstemp(prefix=".notes-beta-", dir=NOTES_PATH.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"notes": items[:NOTE_MAX]}, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, NOTES_PATH)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def add_note(payload: dict) -> dict:
    title = payload.get("title", "")
    content = payload.get("text", payload.get("original", ""))
    if not isinstance(title, str) or not isinstance(content, str):
        raise ValueError("note title and text must be strings")
    title, content = title.strip()[:140], content.strip()[:12000]
    if not content:
        raise ValueError("note text is empty")
    note = {"id": uuid.uuid4().hex, "title": title or content.splitlines()[0][:140],
            "original": content, "status": "inbox"}
    with notes_lock():
        items = read_notes()
        write_notes([note, *items])
    return note


def board_state(info: dict) -> dict:
    """Only facts this customer portal can prove, with no terminal text."""
    project_url, project_local = project_link(info)
    return {"head_session_present": head_session_present(info.get("head_session", "wb-head")),
            "project_url": project_url, "project_local": project_local}


STYLE = """<style>
:root{color-scheme:dark;--bg:#05070a;--panel:#0a0e13;--line:#18222b;
 --ink:#8fa3b0;--bright:#d6e4ec;--dim:#4a5b68;--on:#4fe3c1;
 --off:#2b3a45;--warn:#d9a441}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;min-height:100%;background:var(--bg);color:var(--ink)}
body{font:13px/1.5 ui-monospace,"SF Mono",Menlo,monospace;
 padding:0 16px calc(38px + env(safe-area-inset-bottom));
 background-image:linear-gradient(var(--line) 1px,transparent 1px),
 linear-gradient(90deg,var(--line) 1px,transparent 1px);
 background-size:64px 64px;background-position:-1px -1px;background-attachment:fixed}
body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:2;
 background:repeating-linear-gradient(180deg,rgba(0,0,0,.22) 0 1px,transparent 1px 3px);
 opacity:.5}
a{color:var(--on)}a:focus-visible,button:focus-visible,input:focus-visible,
textarea:focus-visible,.graph-node:focus-visible{outline:2px solid var(--on);outline-offset:3px}
main{max-width:860px;margin:0 auto}
.board-head{position:sticky;top:0;z-index:3;margin:0 -16px 22px;padding:14px 16px;
 padding-top:calc(14px + env(safe-area-inset-top));background:rgba(5,7,10,.93);
 backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
.head-line{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.brand{color:var(--on);letter-spacing:.16em;font-weight:600;text-transform:uppercase}
.machine{color:var(--dim)}.cursor{display:inline-block;width:7px;height:13px;
 background:var(--on);vertical-align:-2px;animation:blink 1.2s steps(1) infinite}
@keyframes blink{50%{opacity:0}}
.meta{margin-left:auto;color:var(--dim);font-size:11px;letter-spacing:.06em}
.meta b{color:var(--on)}.actions{display:flex;gap:10px;margin-top:12px}
.action{display:inline-flex;align-items:center;justify-content:center;gap:8px;
 flex:1;min-height:34px;border:1px solid var(--line);border-radius:3px;
 color:var(--ink);text-decoration:none;font-size:10.5px;letter-spacing:.13em;
 text-transform:uppercase}.action:hover,.action:active{border-color:var(--on);color:var(--on)}
.action i{width:5px;height:5px;background:var(--on);border-radius:50%;
 animation:pulse 2.6s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:.35}50%{opacity:1}}
.board-intro{border:1px solid var(--line);background:var(--panel);padding:13px 14px;
 margin-bottom:20px;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
.board-intro strong{color:var(--bright);font-weight:600}
.board-intro span{color:var(--dim)}
h2{display:flex;align-items:center;gap:12px;margin:26px 0 12px;font-size:11px;
 font-weight:600;letter-spacing:.22em;text-transform:uppercase;color:var(--dim)}
h2::after{content:"";flex:1;height:1px;background:var(--line)}
.grid{display:grid;gap:10px;grid-template-columns:repeat(auto-fill,minmax(150px,1fr))}
.tile{position:relative;display:flex;flex-direction:column;gap:9px;padding:14px;
 min-height:128px;background:var(--panel);border:1px solid var(--line);
 border-radius:3px;color:inherit;text-decoration:none;overflow:hidden;
 transition:border-color .14s,transform .14s,background .14s}
a.tile:active{transform:scale(.975);border-color:var(--on);background:#0d1319}
@media(hover:hover){a.tile:hover{border-color:var(--on);background:#0d1319}}
a.tile:hover .name,a.tile:active .name{color:var(--on)}
.tile.down,.tile.host{opacity:.64}.tile .top{display:flex;justify-content:space-between}
.ico{width:24px;height:24px;color:var(--on);flex:none}
.tile.down .ico,.tile.host .ico{color:var(--off)}
.lamp{width:6px;height:6px;border-radius:50%;margin-top:3px;background:var(--off)}
.tile.up .lamp{background:var(--on);box-shadow:0 0 0 3px rgba(79,227,193,.14)}
.tile.host .lamp{background:var(--warn)}
.name{color:var(--bright);font-weight:600;letter-spacing:.02em;line-height:1.25}
.blurb{color:var(--dim);font-size:11px;line-height:1.35}
.foot{display:flex;justify-content:space-between;align-items:center;gap:7px;
 margin-top:auto;padding-top:8px;font-size:10.5px;color:var(--dim);letter-spacing:.04em}
.status{white-space:nowrap}.beta{color:var(--on);border:1px solid rgba(79,227,193,.4);
 border-radius:2px;padding:0 4px;font-size:9px;letter-spacing:.08em}
.board-footer{margin-top:32px;padding-top:14px;border-top:1px solid var(--line);
 color:var(--dim);font-size:10.5px;line-height:1.7}
.detail{max-width:700px;padding-top:max(22px,env(safe-area-inset-top))}
.back{color:var(--ink);text-decoration:none;font-size:12px}
.back:hover{color:var(--on)}
.eyebrow{color:var(--on);font-size:11px;letter-spacing:.2em;text-transform:uppercase;
 margin-top:30px}h1{font-size:clamp(31px,8vw,48px);font-weight:500;line-height:1.12;
 color:var(--bright);margin:10px 0 17px}
p,small{color:var(--ink)}.panel{border:1px solid var(--line);background:var(--panel);
 border-radius:3px;padding:18px;margin:18px 0}.panel b{color:var(--bright)}
pre{background:#04080b;border:1px solid var(--line);border-radius:3px;padding:14px;
 white-space:pre-wrap;overflow:auto;min-height:40vh;color:var(--bright);font-size:12px}
.button,button{display:inline-block;border:1px solid var(--on);border-radius:3px;
 background:#0b1a17;color:var(--on);padding:10px 14px;font:inherit;
 text-decoration:none;cursor:pointer}
input,textarea{width:100%;background:#070d12;border:1px solid var(--line);
 color:var(--bright);border-radius:3px;padding:10px;font:inherit}
textarea{min-height:130px}label{display:block;margin:15px 0 6px}
.note{border-top:1px solid var(--line);padding:14px 0}.note b{display:block;color:var(--bright)}
.state{color:var(--on);font-size:11px;letter-spacing:.1em}
.graph-panel{border:1px solid var(--line);background:var(--panel);padding:8px;
 margin:18px 0}.knowledge-graph{display:block;width:100%;height:auto}
.edge{fill:none;stroke:#315a59;stroke-width:2;marker-end:url(#arrow)}
.graph-node{cursor:pointer}.graph-node rect{fill:#0d1720;stroke:#315a59;stroke-width:1.5}
.graph-node.live rect{stroke:var(--on)}
.graph-node.pending rect{stroke:var(--warn)}
.graph-node text{fill:var(--bright);font:12px ui-monospace,"SF Mono",Menlo,monospace}
.graph-node .label{fill:var(--dim);font-size:9px;letter-spacing:1.2px}
.graph-node:hover rect,.graph-node.selected rect{stroke:var(--on);stroke-width:2.5}
.graph-inspector{min-height:84px}.graph-inspector b{display:block;margin-bottom:5px}
@media(max-width:520px){.head-line .meta{width:100%;margin-left:0;text-align:right}
 .actions{margin-top:10px}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}
 .tile{min-height:142px}.board-intro{display:block}.board-intro span{display:block;margin-top:3px}}
@media(max-width:370px){.tile{padding:11px}.grid{gap:9px}.action{font-size:9px}}
@media(prefers-reduced-motion:reduce){.cursor,.action i{animation:none}}
</style>"""

# The customer board uses the same glyph paths as Fleetdeck's operator board.
# Keep this small reviewed set inline: no operator registry or topology ships.
BOARD_GLYPHS = {
    "fleet": '<path d="M4 5h16v11H9l-5 4z"/><path d="m8 8.4 2.4 2.1L8 12.6"/><path d="M12.6 12.6h4"/>',
    "messages": '<path d="M20 4H4v12h4v4l5-4h7z"/><path d="M8 10h8"/>',
    "nodes": '<circle cx="6" cy="7" r="2.4"/><circle cx="18" cy="7" r="2.4"/><circle cx="12" cy="17.5" r="2.4"/><path d="M8.4 7h7.2M7.5 9.2l3 6.2M16.5 9.2l-3 6.2"/>',
    "terminal": '<path d="M4 5h16v14H4z"/><path d="m8 10 2.5 2L8 14"/><path d="M13 15h3"/>',
    "script": '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/><path d="M8.5 14.5h1.6l1.4-3.2 1.6 6 1.4-2.8h1"/>',
    "rocket": '<path d="M12 3c3.5 2.5 5 6 5 10l-2.5 3h-5L7 13c0-4 1.5-7.5 5-10z"/><circle cx="12" cy="10" r="1.6"/><path d="M9.5 17 8 21l3-1.5M14.5 17l1.5 4-3-1.5"/>',
}


def board_icon(name: str) -> str:
    return ('<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" '
            'aria-hidden="true">' + BOARD_GLYPHS[name] + '</svg>')


def board_tile(service: str, name: str, blurb: str, icon: str, href: str,
               reach: str, foot: str, status: str) -> str:
    external = ' rel="noreferrer" referrerpolicy="no-referrer"' if href.startswith("https://") else ""
    return (f'<a class="tile {reach}" data-service="{service}" '
            f'href="{html.escape(href, quote=True)}"{external}>'
            f'<div class="top">{board_icon(icon)}<span class="lamp" aria-hidden="true"></span></div>'
            f'<div><div class="name">{html.escape(name)}</div>'
            f'<div class="blurb">{html.escape(blurb)}</div></div>'
            f'<div class="foot"><span>{html.escape(foot)}</span>'
            f'<span class="status">{html.escape(status)}</span></div></a>')


def page(title: str, body: str, info: dict, *, prefix: str = "", board: bool = False) -> str:
    os_name = html.escape(info["os_name"])
    main_class = "" if board else ' class="detail"'
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            f'<meta name="color-scheme" content="dark">'
            f'<meta name="theme-color" content="#05070a">'
            f'<meta name="apple-mobile-web-app-capable" content="yes">'
            f'<meta name="mobile-web-app-capable" content="yes">'
            f'<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">'
            f'<meta name="apple-mobile-web-app-title" content="{os_name}">'
            f'<link rel="apple-touch-icon" href="{prefix}/icon-192.png">'
            f'<link rel="manifest" href="{prefix}/phone.webmanifest">'
            f'<title>{html.escape(title)} · {os_name}</title>{STYLE}</head>'
            f'<body><main{main_class}>{body}</main></body></html>')


def home_page(info: dict, prefix: str = "") -> str:
    goal = {"research": "Research", "website": "Build a website",
            "proposal": "Create a proposal"}[info["first_goal"]]
    state = board_state(info)
    session = state["head_session_present"]
    url = state["project_url"]
    local = state["project_local"]
    project_reach = "up" if url else ("host" if local else "down")
    project_status = "phone ready" if url else ("Mac only" if local else "pending")
    ready = 3 + int(session) + int(bool(url))  # board, graph, notes; session and project need proof
    fleet = "".join((
        board_tile("agent", "Head agent", f'{info["agent_name"]} · your assigned session',
                   "fleet", prefix + "/agent", "up" if session else "down", "wb-head",
                   "session present" if session else "session pending"),
        board_tile("messages", "Messages", "Guide to your separate Apple Account conversation",
                   "messages", prefix + "/agent", "host", "iMessage", "setup guide"),
        board_tile("graph", "Knowledge Graph", "Your local OS and message architecture",
                   "nodes", prefix + "/graph", "up", "local", "ready"),
        board_tile("watch", "Live Terminal", "Head session output · no keyboard access",
                   "terminal", prefix + "/watch", "up" if session else "down", "read only",
                   "session present" if session else "session pending"),
    ))
    workspace = "".join((
        board_tile("project", "First project", goal, "rocket", url or prefix + "/project",
                   project_reach, "HTTPS" if url else "first goal", project_status),
        board_tile("notes", "Notes β", "Capture ideas on this Mac",
                   "script", prefix + "/notes", "up", "beta", "ready"),
    ))
    body = (
        '<header class="board-head"><div class="head-line">'
        '<span class="brand">FLEETDECK</span>'
        f'<span class="machine">// {html.escape(info["os_name"])}</span>'
        '<span class="cursor" aria-hidden="true"></span>'
        f'<span class="meta"><b id="ready-count">{ready}/5</b> ready'
        ' <span id="clock"></span></span></div>'
        '<nav class="actions" aria-label="Board shortcuts">'
        f'<a class="action" href="{prefix}/graph"><i aria-hidden="true"></i>Knowledge graph</a>'
        f'<a class="action" href="{prefix}/watch">Live terminal</a></nav></header>'
        '<div class="board-intro"><strong>Your OS is taking shape</strong>'
        f'<span>{html.escape(info["agent_name"])} · {html.escape(goal)}</span></div>'
        '<section aria-labelledby="fleet-heading"><h2 id="fleet-heading">Fleet</h2>'
        f'<div class="grid">{fleet}</div></section>'
        '<section aria-labelledby="workspace-heading"><h2 id="workspace-heading">Workspace</h2>'
        f'<div class="grid">{workspace}</div></section>'
        '<footer class="board-footer">Only this Mac’s starter services are shown. '
        'The terminal view is read only; Notes is a beta stored on this Mac.</footer>'
        '<script>'
        'function tick(){const d=new Date();document.getElementById("clock").textContent='
        '" · "+String(d.getHours()).padStart(2,"0")+":"+String(d.getMinutes()).padStart(2,"0")}'
        'function setTile(key,reach,status){const t=document.querySelector(\'[data-service="\'+key+\'"]\');'
        'if(!t)return;t.classList.remove("up","host","down");t.classList.add(reach);'
        't.querySelector(".status").textContent=status}'
        f'async function refreshBoard(){{try{{const r=await fetch("{prefix}/api/board",{{cache:"no-store"}});'
        'if(!r.ok)return;const s=await r.json();'
        'document.getElementById("ready-count").textContent='
        '(3+Number(!!s.head_session_present)+Number(!!s.project_url))+"/5";'
        'setTile("agent",s.head_session_present?"up":"down",'
        's.head_session_present?"session present":"session pending");'
        'setTile("watch",s.head_session_present?"up":"down",'
        's.head_session_present?"session present":"session pending");'
        'setTile("project",s.project_url?"up":s.project_local?"host":"down",'
        's.project_url?"phone ready":s.project_local?"Mac only":"pending");'
        'const p=document.querySelector(\'[data-service="project"]\');'
        f'p.href=s.project_url||"{prefix}/project";'
        'p.querySelector(".foot span").textContent=s.project_url?"HTTPS":"first goal"'
        '}catch(e){}}tick();setInterval(tick,10000);refreshBoard();'
        'setInterval(refreshBoard,12000)</script>'
    )
    return page("Board", body, info, prefix=prefix, board=True)


def graph_page(info: dict, prefix: str = "") -> str:
    """A customer-local, inspectable map of the first agent architecture."""
    goal = {"research": "Research", "website": "Build a website",
            "proposal": "Create a proposal"}[info["first_goal"]]
    state = board_state(info)

    def node(key: str, layer: str, title: str, detail: str,
             x: int, y: int, reach: str = "") -> str:
        short = title if len(title) <= 17 else title[:16] + "…"
        safe_title = html.escape(title, quote=True)
        return (f'<g class="graph-node {reach}" data-node="{key}" '
                f'data-title="{safe_title}" data-detail="{html.escape(detail, quote=True)}" '
                f'tabindex="0" role="button" aria-label="{safe_title}: {html.escape(detail, quote=True)}">'
                f'<title>{html.escape(title)}</title>'
                f'<rect x="{x}" y="{y}" width="136" height="62" rx="4"/>'
                f'<text class="label" x="{x + 11}" y="{y + 20}">{html.escape(layer)}</text>'
                f'<text x="{x + 11}" y="{y + 43}">{html.escape(short)}</text></g>')

    nodes = "".join((
        node("os", "OPERATING SYSTEM", info["os_name"],
             "Your named operating system on this Mac.", 112, 20),
        node("owner", "START", "Owner text",
             "You send a text from your own phone to the agent's separate Apple Account.", 15, 130),
        node("listener", "RECEIVE", "Messages listener",
             "The local listener watches the agent Mac's Messages account.", 209, 130),
        node("binding", "ROUTE", "Bound chat",
             "The router accepts only the owner's confirmed one-to-one chat.", 15, 240),
        node("head", "AGENT SESSION", info["agent_name"],
             "The persistent head session receives the routed request.",
             209, 240, "live" if state["head_session_present"] else "pending"),
        node("outbox", "SEND", "Guarded outbox",
             "A guarded worker checks the bound chat before sending a reply.", 15, 350),
        node("reply", "FINISH", "Reply on phone",
             "The answer appears in the same Messages conversation.", 209, 350),
        node("project", "FIRST JOB", goal,
             "Your first project opens from the board when its private HTTPS link is verified.",
             112, 500, "live" if state["project_url"] else "pending"),
    ))
    body = (
        f'<a class="back" href="{prefix}/board">‹ Board</a>'
        f'<div class="eyebrow">{html.escape(info["os_name"])} / Knowledge graph</div>'
        '<h1>Your first agent architecture</h1>'
        '<p>Tap a node to inspect the path from your first text to the reply. '
        'Green outlines mark the session and project only when this Mac can verify them.</p>'
        '<div class="graph-panel"><svg class="knowledge-graph" viewBox="0 0 360 590" '
        'role="group" aria-label="Interactive agent architecture graph">'
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" '
        'markerWidth="5" markerHeight="5" orient="auto-start-reverse">'
        '<path d="M0 0 10 5 0 10z" fill="#315a59"/></marker></defs>'
        '<path class="edge" d="M180 82 L83 130"/>'
        '<path class="edge" d="M151 161 H209"/>'
        '<path class="edge" d="M277 192 C277 218 83 218 83 240"/>'
        '<path class="edge" d="M151 271 H209"/>'
        '<path class="edge" d="M277 302 C277 328 83 328 83 350"/>'
        '<path class="edge" d="M151 381 H209"/>'
        '<path class="edge" d="M277 302 C315 445 180 448 180 500"/>'
        f'{nodes}</svg></div>'
        '<div class="panel graph-inspector" id="graph-inspector" role="status" aria-live="polite">'
        '<b>Choose a node</b><span>Each layer has one job in the first text path.</span></div>'
        '<script>'
        'const nodes=document.querySelectorAll(".graph-node");'
        'function inspect(n){nodes.forEach(x=>x.classList.remove("selected"));'
        'n.classList.add("selected");const box=document.getElementById("graph-inspector");'
        'box.querySelector("b").textContent=n.dataset.title;'
        'box.querySelector("span").textContent=n.dataset.detail}'
        'nodes.forEach(n=>{n.addEventListener("click",()=>inspect(n));'
        'n.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){'
        'e.preventDefault();inspect(n)}})})'
        '</script>'
    )
    return page("Knowledge graph", body, info, prefix=prefix)


def detail_page(kind: str, info: dict, prefix: str = "") -> str:
    os_name, agent = html.escape(info["os_name"]), html.escape(info["agent_name"])
    goal = {"research": "Research", "website": "Build a website",
            "proposal": "Create a proposal"}[info["first_goal"]]
    intro = f'<a class="back" href="{prefix}/board">‹ Board</a>'
    if kind == "agent":
        body = (intro + f'<div class="eyebrow">{os_name} / Head agent</div><h1>{agent}</h1>'
                '<div class="panel"><b>Talk in Messages</b><p>Open your conversation with the separate Apple Account signed into Messages on this Mac.</p>'
                '<small>Apple Account passwords and verification codes stay in Apple’s sign-in.</small></div>'
                f'<a class="button" href="{prefix}/watch">Watch {agent} work →</a>')
    elif kind == "graph":
        return graph_page(info, prefix)
    elif kind == "project":
        url, live = project_link(info)
        detail = ('Your website is running on this Mac. An HTTPS phone link is still pending.'
                  if live else f'Text {agent} your first {goal.lower()} request to begin.')
        action = (f'<p><a class="button" href="{html.escape(url, quote=True)}" '
                  'rel="noreferrer" referrerpolicy="no-referrer">Open project →</a></p>'
                  if url else "")
        body = intro + f'<div class="eyebrow">{os_name} / First project</div><h1>{goal}</h1><div class="panel"><p>{detail}</p>{action}</div>'
    elif kind == "watch":
        body = (intro + f'<div class="eyebrow">{os_name} / Live terminal</div><h1>Watch {agent}</h1>'
                '<p>This view is read only.</p><div class="state" id="state" role="status">Connecting…</div>'
                '<pre id="pane" aria-label="Head agent terminal"></pre>'
                f'<script>async function refresh(){{try{{const r=await fetch("{prefix}/api/watch",{{cache:"no-store"}});const d=await r.json();'
                'document.getElementById("state").textContent=d.running?"LIVE · READ ONLY":"SESSION NOT RUNNING";'
                'document.getElementById("pane").textContent=d.running?d.text:"The head agent session is not running yet.";'
                '}catch(e){document.getElementById("state").textContent="CONNECTION LOST"}}refresh();setInterval(refresh,3000)</script>')
    else:
        raise ValueError("unknown page")
    return page(kind.title(), body, info, prefix=prefix)


def notes_page(info: dict, prefix: str = "") -> str:
    body = (f'<a class="back" href="{prefix}/board">‹ Board</a><div class="eyebrow">Ideas / Beta</div>'
            '<h1>Notes <span class="beta">BETA</span></h1><p>Capture an idea on this phone board. Existing Fleetdeck Notes are not imported or synced into this beta.</p>'
            '<form id="form"><label for="title">Title (optional)</label><input id="title" maxlength="140">'
            '<label for="text">Idea</label><textarea id="text" maxlength="12000" required></textarea>'
            '<p><button type="submit">Save note</button></p></form><div class="state" id="state"></div>'
            '<div id="items"></div><script>'
            f'async function load(){{const r=await fetch("{prefix}/api/notes",{{cache:"no-store"}});const d=await r.json();'
            'const root=document.getElementById("items");root.replaceChildren();'
            'for(const n of d.notes){const row=document.createElement("div");row.className="note";'
            'const title=document.createElement("b");title.textContent=n.title;'
            'const text=document.createElement("p");text.textContent=n.original;row.append(title,text);root.append(row)}}'
            'document.getElementById("form").onsubmit=async(e)=>{e.preventDefault();const b={title:document.getElementById("title").value,text:document.getElementById("text").value};'
            f'const r=await fetch("{prefix}/api/notes",{{method:"POST",headers:{{"Content-Type":"application/json"}},body:JSON.stringify(b)}});'
            'document.getElementById("state").textContent=r.ok?"Saved":"Could not save note";'
            'if(r.ok){document.getElementById("text").value="";document.getElementById("title").value="";load()}};load();'
            '</script>')
    return page("Notes beta", body, info, prefix=prefix)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def send(self, code: int, body: bytes | str, mime: str = "text/plain; charset=utf-8") -> None:
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, code: int, value: object) -> None:
        self.send(code, json.dumps(value, ensure_ascii=False), "application/json; charset=utf-8")

    def forbidden(self) -> None:
        self.close_connection = True
        self.send(403, b"")

    def do_GET(self) -> None:
        raw_path = self.path.split("?", 1)[0]
        if raw_path == "/healthz":
            ready = onboarding_config() is not None and access_token() is not None
            return self.send(200 if ready else 503, "ok\n" if ready else "setup pending\n")
        authorized = capability_route(raw_path)
        if authorized is None:
            return self.forbidden()
        route, prefix = authorized
        info = onboarding_config()
        if not info:
            return self.send(503, "Fleetdeck setup is pending\n")
        if route in ("/", "/phone", "/board"):
            return self.send(200, home_page(info, prefix), "text/html; charset=utf-8")
        if route in ("/agent", "/graph", "/project", "/watch"):
            return self.send(200, detail_page(route[1:], info, prefix), "text/html; charset=utf-8")
        if route == "/notes":
            return self.send(200, notes_page(info, prefix), "text/html; charset=utf-8")
        if route == "/api/watch":
            text = head_session_snapshot(info["head_session"])
            return self.send_json(200, {"running": text is not None, "text": text or ""})
        if route == "/api/board":
            return self.send_json(200, board_state(info))
        if route == "/api/notes":
            try:
                with notes_lock():
                    notes = read_notes()
            except (OSError, ValueError):
                return self.send_json(503, {"error": "notes store unavailable"})
            return self.send_json(200, {"notes": notes})
        if route == "/phone.webmanifest":
            manifest = {"name": info["os_name"], "short_name": info["os_name"],
                        "start_url": prefix + "/board", "scope": prefix + "/",
                        "display": "fullscreen",
                        "display_override": ["fullscreen", "standalone"],
                        "background_color": "#05070a", "theme_color": "#05070a",
                        "icons": [{"src": prefix + "/icon-192.png", "sizes": "192x192", "type": "image/png"},
                                  {"src": prefix + "/icon-512.png", "sizes": "512x512", "type": "image/png"}]}
            return self.send_json(200, manifest)
        if route in ("/icon-192.png", "/icon-512.png"):
            icon = HERE / "assets" / route.lstrip("/")
            try:
                return self.send(200, icon.read_bytes(), "image/png")
            except OSError:
                return self.send(404, "not found\n")
        return self.send(404, "not found\n")

    def do_POST(self) -> None:
        authorized = capability_route(self.path.split("?", 1)[0])
        if authorized is None:
            return self.forbidden()
        route, _ = authorized
        if route != "/api/notes" or not onboarding_config():
            return self.forbidden()
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            return self.send_json(415, {"error": "JSON content type required"})
        origin = self.headers.get("Origin")
        if origin:
            try:
                parsed = urlsplit(origin)
            except ValueError:
                return self.send_json(403, {"error": "cross-origin notes request refused"})
            if (parsed.scheme not in ("http", "https")
                    or parsed.netloc != self.headers.get("Host", "")
                    or parsed.path or parsed.query or parsed.fragment):
                return self.send_json(403, {"error": "cross-origin notes request refused"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > BODY_MAX:
                return self.send_json(413, {"error": "note too large"})
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("expected an object")
            note = add_note(body)
        except (OSError, ValueError, UnicodeError) as error:
            return self.send_json(400, {"error": str(error)[:120]})
        return self.send_json(200, {"note": note})

    def do_PUT(self) -> None:
        self.forbidden()

    def do_DELETE(self) -> None:
        self.forbidden()


def main() -> None:
    settings = config()
    port = int(os.environ.get("FLEETDECK_PORT", settings.get("ports", {}).get("portal", 8790)))
    bind = os.environ.get("FLEETDECK_BIND", "127.0.0.1")
    if bind != "127.0.0.1":
        raise SystemExit("customer portal requires a loopback bind")
    with ThreadingHTTPServer((bind, port), Handler) as server:
        server.daemon_threads = True
        server.serve_forever()


if __name__ == "__main__":
    main()
