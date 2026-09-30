#!/usr/bin/env python3
"""Build and verify the current Fleetdeck board for a customer Mac.

The actual tracked Fleetdeck portal provides the board and live service scan.
A reviewed transformation removes operator identity and installs a narrow,
owner-authenticated HTTP adapter before that source is bundled.
"""

from __future__ import annotations

import hashlib
import ast
import fcntl
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile


MANIFEST = ".wideband-fleetdeck-bundle.json"
LEGACY_SOURCE_FILES = {
    "install.sh",
    "bin/fleetdeck",
    "VERSION",
    "LICENSE",
    "NOTICE",
    "launchagents/fleetdeck-portal.plist.tmpl",
    "assets/icon-192.png",
    "assets/icon-512.png",
}
LEGACY_GENERATED_FILES = {"portal_server.py", "config.example.json", "services.example.json"}
LEGACY_REQUIRED = LEGACY_SOURCE_FILES | LEGACY_GENERATED_FILES
SOURCE_FILES = LEGACY_SOURCE_FILES | {
    "glyphs.json", "make-icons.py", "assets/icon-180.png",
    "launchagents/fleetdeck-chat.plist.tmpl", "ttyd-index.html",
}
GENERATED_FILES = LEGACY_GENERATED_FILES | {"chat_server.py", "customer_access.py"}
REQUIRED = SOURCE_FILES | GENERATED_FILES
UPGRADE_FILES = GENERATED_FILES | {"glyphs.json", "make-icons.py", "assets/icon-180.png"}
BRAND_VIDEO = "assets/wb-logo-256.mp4"
BRAND_VIDEO_MAX_BYTES = 512_000
PORTAL_NAME = "portal_server.py"
CHAT_NAME = "chat_server.py"
AUTH_ADAPTER_SOURCE = Path(__file__).with_name("fleetdeck-customer-auth.pyinc")
ACCESS_SOURCE = Path(__file__).with_name("fleetdeck-customer-access.py")
PRIVATE_NAMES = {".git", "auth", "config.json", "services.json", ".fleetdeck-notes.json"}
PRIVATE_DIRS = {"backup", "backups", "notes"}
STATIC_IDENTITY = re.compile(
    rb"(?i)(?:[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}|[a-z0-9.-]+\.ts\.net)"
)
PHONE_IDENTITY = re.compile(rb"\+[1-9][0-9]{10,14}\b")
OPERATOR_SOURCE_MARKERS = (b"Instant iMessage Agent Installer",)
NOTES_AGE_SOURCE = " function ago(ts){\n   var s = Math.max(0, Math.floor(Date.now()/1000 - ts));"
NOTES_AGE_PILOT = (" function ago(ts){\n"
                   "   if (!Number.isFinite(Number(ts)) || Number(ts) <= 0) return 'saved';\n"
                   "   var s = Math.max(0, Math.floor(Date.now()/1000 - ts));")
UPSTREAM_PORTAL_PATH = "__HOME__/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
INITIAL_PORTAL_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"


def optional_assets(paths: set[str]) -> set[str]:
    """Only reviewed public art, including the one fixed Wideband video mark."""
    images = {name for name in paths if (
        (name.startswith("icons/") and name.count("/") == 1)
        or (name.startswith("assets/glyphs/") and name.count("/") == 2)
    ) and name.endswith(".png")}
    return images | ({BRAND_VIDEO} if BRAND_VIDEO in paths else set())


def check_brand_video(path: Path) -> None:
    """Keep a tracked, small MP4 at the one reviewed public asset path."""
    if not regular_file(path) or not 12 <= path.stat().st_size <= BRAND_VIDEO_MAX_BYTES:
        raise ValueError("Wideband logo video is missing, unsafe, or too large")
    with path.open("rb") as stream:
        header = stream.read(12)
    if header[4:8] != b"ftyp" or int.from_bytes(header[:4], "big") < 12:
        raise ValueError("Wideband logo video is not an MP4")


def replace_assignment(source: str, name: str, expression: str) -> str:
    """Replace one top-level assignment by AST span, failing on source drift."""
    tree = ast.parse(source)
    nodes = [node for node in tree.body if isinstance(node, ast.Assign)
             and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
             and node.targets[0].id == name]
    if len(nodes) != 1:
        raise ValueError(f"Fleetdeck portal assignment changed: {name}")
    node = nodes[0]
    lines = source.splitlines(keepends=True)
    lines[node.lineno - 1:node.end_lineno] = [f"{name} = {expression}\n"]
    return "".join(lines)


def customer_portal(source: str) -> str:
    """Keep Fleetdeck's board/scan source; remove host data and gate routes."""
    required = (
        "class Handler(BaseHTTPRequestHandler):", "def scan():", "PAGE =",
        "NOTES_PAGE =", "def onboarding_config():", "def main():", "INTERNAL = {",
        "ThreadingHTTPServer((BIND, PORT), Handler)",
    )
    if any(item not in source for item in required):
        raise ValueError("Fleetdeck portal source changed; review customer transform")
    chip = ('<a id="cashflow" href="/cashflow"\n'
            '     title="Cashflow — the accountant\'s cash view">__CASHFLOW_LABEL__</a>')
    if source.count(chip) != 1 or source.count("#cashflow") != 5:
        raise ValueError("Fleetdeck board Notes slot changed; review customer transform")
    changes = {
        "SEED_NOTES": "[]",
        "OPERATOR_PHONE": 'os.environ.get("WB_OPERATOR_PHONE", "")',
        "TRACE_IMESSAGE_HANDLE": 'os.environ.get("WB_AGENT_IMESSAGE_HANDLE", CONF.get("agent_imessage_handle", ""))',
        "NETMAP_URL": '""',
        "CASHFLOW_PATH": 'os.environ.get("FLEETDECK_CASHFLOW_PATH", "")',
        "WHISPER_MODEL": 'os.environ.get("WB_WHISPER_MODEL", "")',
        "VOICE_URL": 'os.environ.get("WB_VOICE_URL", "")',
        "NOTES_PATH": 'os.path.expanduser(os.environ.get("FLEETDECK_NOTES_PATH", "~/.wideband/fleetdeck/notes-beta.json"))',
        "TRACE_SESSION": 'os.environ.get("WB_TRACE_SESSION", "wb-head")',
    }
    for name, expression in changes.items():
        source = replace_assignment(source, name, expression)
    # Customer mode has no direct outbound iMessage path. The private outbox
    # worker owns sends; retaining the operator's binary literal is unsafe on
    # a Mac where /opt/homebrew belongs to another profile.
    if "def send_text(" in source:
        source = replace_assignment(source, "IMSG", '""')
    if source.count(NOTES_AGE_SOURCE) != 1:
        raise ValueError("Fleetdeck Notes age renderer changed; review legacy notes")
    source = source.replace(NOTES_AGE_SOURCE, NOTES_AGE_PILOT, 1)
    # Historical comments also name the operator's own contact and tailnet.
    # Scrub by shape rather than recording those values in this public repo.
    source = re.sub(r"(?i)[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}",
                    "the agent Apple Account", source)
    source = re.sub(r"(?i)[a-z0-9.-]+\.ts\.net", "the configured tailnet host", source)
    source = re.sub(r"\+[1-9][0-9]{10,14}\b", "", source)
    marker = "\ndef main():"
    source = source.replace(marker, "\n" + AUTH_ADAPTER_SOURCE.read_text(encoding="utf-8")
                            + "\nCUSTOMER_PORTAL_ADAPTER_VERSION = 1\n" + marker, 1)
    source = source.replace("ThreadingHTTPServer((BIND, PORT), Handler)",
                            "ThreadingHTTPServer((BIND, PORT), CustomerHandler)", 1)
    compile(source, PORTAL_NAME, "exec")
    if STATIC_IDENTITY.search(source.encode()) or PHONE_IDENTITY.search(source.encode()) or any(
            marker in source.encode() for marker in OPERATOR_SOURCE_MARKERS):
        raise ValueError("operator identifier remains in customer portal")
    return source


def customer_portal_template(source: str) -> str:
    """Keep the first portal launch on system PATH until the verified bin is set."""
    if not source.lstrip().startswith("<?xml"):
        return source  # Minimal source fixtures do not carry a real plist.
    if source.count(UPSTREAM_PORTAL_PATH) != 1:
        raise ValueError("Fleetdeck portal PATH changed; review customer transform")
    return source.replace(UPSTREAM_PORTAL_PATH, INITIAL_PORTAL_PATH, 1)


def customer_chat_tools(source: str) -> str:
    """Keep tmux and ttyd resolution inside the managed LaunchAgent PATH."""
    if "def _bin(" not in source:
        return source  # Minimal source fixtures omit the upstream resolver.
    source = replace_assignment(source, "TMUX", '_bin("tmux")')
    source = replace_assignment(source, "TTYD", '_bin("ttyd")')
    return source


def customer_chat(source: str) -> str:
    """Preserve the current chat UI for later opt-in, closed under customer mode."""
    source = customer_chat_tools(source)
    tree = ast.parse(source)
    handler = next((node for node in tree.body if isinstance(node, ast.ClassDef)
                    and node.name == "H"), None)
    if handler is None or "if customer_mode():" not in source:
        raise ValueError("Fleetdeck chat customer guard changed")
    names = {"authed", "try_key"}
    funcs = [node for node in handler.body if isinstance(node, ast.FunctionDef)
             and node.name in names]
    if {node.name for node in funcs} != names:
        raise ValueError("Fleetdeck chat auth methods changed")
    lines = source.splitlines(keepends=True)
    # Replace from the bottom so the AST line numbers remain valid.
    methods = {
        "authed": ('    def authed(self):\n'
                   '        capability = customer_access.token()\n'
                   '        if (os.environ.get("FLEETDECK_LOCAL_ONLY") == "1"\n'
                   '                and not customer_access.local_http_request(\n'
                   '                    self.headers.get("Host"), PORT)):\n'
                   '            self.reply(403, {"error": "forbidden host"})\n'
                   '            return False\n'
                   '        if capability and customer_access.has_session(\n'
                   '                self.headers.get("Cookie"), capability):\n'
                   '            return True\n'
                   '        self.reply(403, {"error": "forbidden"})\n'
                   '        return False\n'),
        "try_key": ('    def try_key(self):\n'
                    '        return False\n'),
    }
    for node in sorted(funcs, key=lambda item: item.lineno, reverse=True):
        lines[node.lineno - 1:node.end_lineno] = [methods[node.name]]
    source = "".join(lines)
    query_branch = '        if self.path.startswith("/?key=") and self.try_key():\n            return\n'
    if source.count(query_branch) != 1:
        raise ValueError("Fleetdeck chat query-key branch changed")
    token_branch = (
        '        match = re.fullmatch(r"/p/([0-9a-f]{64})/chat", self.path.split("?", 1)[0])\n'
        '        if match:\n'
        '            if (os.environ.get("FLEETDECK_LOCAL_ONLY") == "1"\n'
        '                    and not customer_access.local_http_request(\n'
        '                        self.headers.get("Host"), PORT)):\n'
        '                return self.reply(403, {"error": "forbidden host"})\n'
        '            capability = customer_access.token()\n'
        '            if not capability or not hmac.compare_digest(match.group(1), capability):\n'
        '                return self.reply(403, {"error": "forbidden"})\n'
        '            self.send_response(303)\n'
        '            self.send_header("Location", "/")\n'
        '            self.send_header("Set-Cookie", customer_access.cookie_header(\n'
        '                capability, secure=not customer_access.local_http_request(\n'
        '                    self.headers.get("Host"), PORT)))\n'
        '            self.send_header("Referrer-Policy", "no-referrer")\n'
        '            self.send_header("Content-Length", "0")\n'
        '            self.end_headers()\n'
        '            return\n')
    source = source.replace(query_branch, token_branch, 1)
    source = source.replace("import os, re, io, json, time, base64, socket, colorsys, hashlib, signal, stat",
                            "import os, re, io, json, time, base64, socket, colorsys, hashlib, signal, stat\nimport hmac\nimport customer_access", 1)
    origin_guard = '''def customer_board_origin():
    """Trust the configured tailnet host or dedicated loopback preview."""
    host = os.environ.get("FLEETDECK_HOST", "")
    if os.environ.get("FLEETDECK_LOCAL_ONLY") == "1":
        return "http://wideband.localhost:8790" if host == "wideband.localhost" else ""
    if len(host) > 253 or not re.fullmatch(
            r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\\.){2,}ts\\.net", host):
        return ""
    return f"https://{host}:8790"


CUSTOMER_BOARD_ORIGIN = customer_board_origin()
if not CUSTOMER_BOARD_ORIGIN:
    raise SystemExit(78)
CUSTOMER_FRAME_POLICY = "frame-ancestors 'self' " + CUSTOMER_BOARD_ORIGIN


def customer_write_origin(headers):
    """Only this origin may drive a customer tmux terminal."""
    host = headers.get("Host", "")
    if not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]{1,5})?", host):
        return False
    if (os.environ.get("FLEETDECK_LOCAL_ONLY") == "1"
            and host != f"wideband.localhost:{PORT}"):
        return False
    origin = headers.get("Origin")
    expected = ("http" if os.environ.get("FLEETDECK_LOCAL_ONLY") == "1"
                or host.startswith(("127.0.0.1:", "localhost:"))
                else "https") + "://" + host
    if origin and origin != expected:
        return False
    return headers.get("Sec-Fetch-Site") in (None, "same-origin", "none")


'''
    marker = "class H(BaseHTTPRequestHandler):"
    if source.count(marker) != 1:
        raise ValueError("Fleetdeck chat handler changed")
    source = source.replace(marker, origin_guard + marker, 1)
    ws_guard = ('        path = self.path.split("?")[0]\n'
                '        if path == BASE or path.startswith(BASE + "/"):\n'
                '            return self.proxy()\n')
    if ws_guard not in source or source.index(ws_guard) > source.index("    def do_POST(self):"):
        raise ValueError("Fleetdeck chat WebSocket route changed")
    source = source.replace(ws_guard,
                            '        path = self.path.split("?")[0]\n'
                            '        if path == BASE or path.startswith(BASE + "/"):\n'
                            '            if self.headers.get("Upgrade", "").lower() == "websocket" and not customer_write_origin(self.headers):\n'
                            '                return self.reply(403, {"error": "forbidden origin"})\n'
                            '            return self.proxy()\n', 1)
    post_guard = ('    def do_POST(self):\n'
                  '        if not self.authed():\n'
                  '            return\n')
    if source.count(post_guard) != 1:
        raise ValueError("Fleetdeck chat POST guard changed")
    source = source.replace(post_guard,
                            post_guard +
                            '        if not customer_write_origin(self.headers):\n'
                            '            return self.reply(403, {"error": "forbidden origin"})\n', 1)
    guard = ('    if customer_mode():\n'
             '        print("refusing writable chat in customer mode; use portal /watch", flush=True)\n'
             '        raise SystemExit(78)\n')
    replacement = ('    if (os.environ.get("FLEETDECK_CUSTOMER_TERMINALS") != "1"\n'
                   '            or BIND != "127.0.0.1" or not CUSTOMER_BOARD_ORIGIN):\n'
                   '        print("customer terminals require opt-in, loopback, and a validated board host", flush=True)\n'
                   '        raise SystemExit(78)\n')
    if source.count(guard) != 1:
        raise ValueError("Fleetdeck chat startup guard changed")
    source = source.replace(guard, replacement, 1)
    reply_cache_header = '        self.send_header("Cache-Control", "no-store")\n'
    if source.count(reply_cache_header) != 1:
        raise ValueError("Fleetdeck chat response headers changed")
    source = source.replace(reply_cache_header,
                            reply_cache_header +
                            '        self.send_header("Referrer-Policy", "no-referrer")\n'
                            '        self.send_header("X-Content-Type-Options", "nosniff")\n'
                            '        self.send_header("Content-Security-Policy", CUSTOMER_FRAME_POLICY)\n', 1)
    proxy_head = r'''            if b" 101 " in lines[0]:
                self.wfile.write(buf)
            else:
                kept = [l for l in lines[1:]
                        if not re.match(rb"(?i)(connection|keep-alive)\s*:", l)]
                self.wfile.write(b"\r\n".join([lines[0]] + kept + [b"Connection: close"])
                                 + b"\r\n\r\n" + rest)
'''
    proxy_hardened = r'''            # The browser may frame ttyd only from this exact board origin.
            # Keep upstream CSP directives unrelated to framing.
            kept = []
            for line in lines[1:]:
                name, separator, value = line.partition(b":")
                if not separator:
                    kept.append(line)
                elif name.strip().lower() == b"x-frame-options":
                    continue
                elif name.strip().lower() == b"content-security-policy":
                    directives = [part.strip() for part in value.split(b";") if part.strip()]
                    other = [part for part in directives
                             if not re.match(rb"(?i)frame-ancestors(?:\s|$)", part)]
                    if other:
                        kept.append(b"Content-Security-Policy: " + b"; ".join(other))
                else:
                    kept.append(line)
            frame_policy = b"Content-Security-Policy: " + CUSTOMER_FRAME_POLICY.encode("ascii")
            if b" 101 " in lines[0]:
                self.wfile.write(b"\r\n".join([lines[0]] + kept + [frame_policy])
                                 + b"\r\n\r\n" + rest)
            else:
                kept = [line for line in kept
                        if not re.match(rb"(?i)(connection|keep-alive)\s*:", line)]
                self.wfile.write(b"\r\n".join([lines[0]] + kept
                                           + [frame_policy, b"Connection: close"])
                                 + b"\r\n\r\n" + rest)
'''
    if source.count(proxy_head) != 1:
        raise ValueError("Fleetdeck ttyd response proxy changed")
    source = source.replace(proxy_head, proxy_hardened, 1)
    compile(source, CHAT_NAME, "exec")
    return source


def safe_name(value: str) -> bool:
    path = PurePosixPath(value)
    parts = value.split("/")
    if not value or path.is_absolute() or any(part in {"", ".", ".."} for part in parts):
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return False
    if any(part.lower() in PRIVATE_NAMES or part.lower() in PRIVATE_DIRS for part in parts):
        return False
    if any(part.endswith("~") or ".bak" in part.lower() or ".backup" in part.lower() for part in parts):
        return False
    return value != MANIFEST


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def regular_file(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except OSError:
        return False
    return stat.S_ISREG(mode)


def check_source(root: Path, *, legacy: bool = False) -> None:
    for name in LEGACY_SOURCE_FILES if legacy else SOURCE_FILES:
        if not regular_file(root / name):
            raise ValueError(f"missing tracked Fleetdeck customer file: {name}")
    if "CUSTOMER_MODE" not in (root / "install.sh").read_text(encoding="utf-8"):
        raise ValueError("Fleetdeck install.sh lacks the customer-mode guard")
    if "__ROOT__/portal_server.py" not in (root / "launchagents/fleetdeck-portal.plist.tmpl").read_text(encoding="utf-8"):
        raise ValueError("Fleetdeck LaunchAgent does not point to the customer portal path")


def check_bundle(root: Path, hashes: dict[str, str]) -> None:
    legacy = set(hashes) == LEGACY_REQUIRED
    for name in LEGACY_REQUIRED if legacy else REQUIRED:
        if not regular_file(root / name):
            raise ValueError(f"missing bundled Fleetdeck customer file: {name}")
    check_source(root, legacy=legacy)
    if BRAND_VIDEO in hashes:
        check_brand_video(root / BRAND_VIDEO)
    portal = (root / "portal_server.py").read_text(encoding="utf-8")
    # The first customer portal used `route` for the health request path.
    # Accept that verified release so it can upgrade to the current portal.
    health_markers = ('route == "/healthz"', 'raw_path == "/healthz"',
                      'path == "/healthz"')
    if "def onboarding_config" not in portal or not any(marker in portal for marker in health_markers):
        raise ValueError("Fleetdeck customer portal lacks required routes")
    if not legacy and ("CUSTOMER_PORTAL_ADAPTER_VERSION = 1" not in portal
                       or "def scan():" not in portal
                       or "ThreadingHTTPServer((BIND, PORT), CustomerHandler)" not in portal):
        raise ValueError("actual Fleetdeck customer board adapter is missing")
    if not legacy:
        chat = (root / CHAT_NAME).read_text(encoding="utf-8")
        access = (root / "customer_access.py").read_text(encoding="utf-8")
        template = (root / "launchagents/fleetdeck-chat.plist.tmpl").read_text(encoding="utf-8")
        if ("FLEETDECK_CUSTOMER_TERMINALS" not in chat
                or "customer_access.has_session" not in chat
                or 'self.path.startswith("/?key=")' in chat
                or not ("Secure; HttpOnly; SameSite=Strict" in access
                        or ("Secure; " in access and "local_http_request" in access
                            and "HttpOnly; SameSite=Strict" in access))
                or "<string>127.0.0.1</string>" not in template):
            raise ValueError("Fleetdeck customer terminal guard is missing")


def scan_private(root: Path, names: set[str]) -> None:
    for name in names:
        path = root / name
        data = path.read_bytes()
        if (STATIC_IDENTITY.search(data) or PHONE_IDENTITY.search(data)
                or any(marker in data for marker in OPERATOR_SOURCE_MARKERS)):
            raise ValueError(f"operator identifier found in customer bundle: {name}")


def build(source: Path, target: Path) -> None:
    source = source.resolve(strict=True)
    root = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "--show-toplevel"], text=True
    ).strip()
    if Path(root).resolve() != source:
        raise ValueError("Fleetdeck source must be a repository root")
    names = subprocess.check_output(
        ["git", "-C", str(source), "ls-files", "--cached", "-z"]
    ).split(b"\0")
    paths = [os.fsdecode(name) for name in names if name]
    tracked = set(paths)
    if BRAND_VIDEO not in tracked or not regular_file(source / BRAND_VIDEO):
        raise ValueError("reviewed Wideband logo video is missing or not tracked")
    if not SOURCE_FILES.issubset(tracked | {PORTAL_NAME, CHAT_NAME}):
        raise ValueError("required Fleetdeck customer files are not tracked")
    if not {PORTAL_NAME, CHAT_NAME}.issubset(tracked):
        raise ValueError("actual Fleetdeck portal and chat sources are not tracked")
    for name in paths:
        if not safe_name(name) or not regular_file(source / name):
            raise ValueError(f"unsafe or missing tracked Fleetdeck file: {name!r}")
    check_source(source)
    check_brand_video(source / BRAND_VIDEO)
    for item in (source / PORTAL_NAME, source / CHAT_NAME, AUTH_ADAPTER_SOURCE, ACCESS_SOURCE):
        if not regular_file(item):
            raise ValueError(f"reviewed Fleetdeck source is missing: {item.name}")
    selected = SOURCE_FILES | optional_assets(tracked)
    target.mkdir(parents=True, exist_ok=False)
    try:
        hashes: dict[str, str] = {}
        for name in sorted(selected):
            destination = target / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if name == "launchagents/fleetdeck-portal.plist.tmpl":
                destination.write_text(
                    customer_portal_template((source / name).read_text(encoding="utf-8")),
                    encoding="utf-8")
            elif name == "launchagents/fleetdeck-chat.plist.tmpl":
                template = (source / name).read_text(encoding="utf-8")
                if template.count("<string>tailscale</string>") != 1:
                    raise ValueError("Fleetdeck chat bind template changed")
                destination.write_text(template.replace("<string>tailscale</string>",
                                                        "<string>127.0.0.1</string>", 1),
                                       encoding="utf-8")
            else:
                shutil.copy2(source / name, destination)
            hashes[name] = digest(destination)
        (target / PORTAL_NAME).write_text(
            customer_portal((source / PORTAL_NAME).read_text(encoding="utf-8")),
            encoding="utf-8")
        (target / CHAT_NAME).write_text(
            customer_chat((source / CHAT_NAME).read_text(encoding="utf-8")),
            encoding="utf-8")
        shutil.copy2(ACCESS_SOURCE, target / "customer_access.py")
        (target / "config.example.json").write_text(json.dumps({
            "brand": "fleetdeck", "machine": "", "label_prefix": "com.example",
            "ports": {"portal": 8790, "chat": 8783, "ttyd": 8784, "adopt": 8793},
            "agents": {"show": True, "actions": False, "include": [], "exclude": []},
        }, indent=2) + "\n", encoding="utf-8")
        (target / "services.example.json").write_text(
            json.dumps({"groups": [{"id": "fleet", "label": "fleet"},
                                   {"id": "apps", "label": "apps"},
                                   {"id": "models", "label": "models"},
                                   {"id": "data", "label": "data"}],
                        "services": []}, indent=2) + "\n",
            encoding="utf-8")
        for name in GENERATED_FILES:
            hashes[name] = digest(target / name)
        (target / MANIFEST).write_text(
            json.dumps({"schema_version": 1, "source": "customer-allowlisted-working-tree",
                        "files": hashes}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        verify(target)
    except Exception:
        shutil.rmtree(target)
        raise


def verify_managed(root: Path) -> dict[str, str]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Fleetdeck source bundle path is not a real directory")
    if not regular_file(root / MANIFEST):
        raise ValueError("Fleetdeck source bundle manifest is missing")
    metadata = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    if metadata.get("schema_version") != 1 or metadata.get("source") != "customer-allowlisted-working-tree":
        raise ValueError("unsupported Fleetdeck source bundle")
    hashes = metadata.get("files")
    if (not isinstance(hashes, dict)
            or (set(hashes) != LEGACY_REQUIRED and
                (not REQUIRED.issubset(hashes)
                 or set(hashes) - REQUIRED != optional_assets(set(hashes))))):
        raise ValueError("Fleetdeck source bundle file list is incomplete")
    if any(not isinstance(name, str) or not safe_name(name) or not isinstance(value, str)
           or len(value) != 64 for name, value in hashes.items()):
        raise ValueError("unsafe Fleetdeck source bundle file list")
    for name, expected in hashes.items():
        parent = root
        for part in PurePosixPath(name).parts[:-1]:
            parent = parent / part
            if parent.is_symlink():
                raise ValueError(f"Fleetdeck source bundle path contains a symlink: {name}")
        if not regular_file(root / name) or digest(root / name) != expected:
            raise ValueError(f"Fleetdeck source bundle checksum mismatch: {name}")
    check_bundle(root, hashes)
    scan_private(root, set(hashes))
    return hashes


def verify(root: Path) -> None:
    hashes = verify_managed(root)
    actual: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Fleetdeck source bundle contains a symlink: {path}")
        if path.is_dir():
            if not safe_name(path.relative_to(root).as_posix()):
                raise ValueError(f"unsafe Fleetdeck source bundle directory: {path}")
            continue
        name = path.relative_to(root).as_posix()
        if not regular_file(path) or (name != MANIFEST and not safe_name(name)):
            raise ValueError(f"unsafe Fleetdeck source bundle file: {name}")
        if name != MANIFEST:
            actual.add(name)
    if actual != set(hashes):
        raise ValueError("Fleetdeck source bundle contains missing or extra files")


def check_current(bundle: Path, installed: Path) -> None:
    verify(bundle)
    expected = verify_managed(installed)
    packaged = json.loads((bundle / MANIFEST).read_text(encoding="utf-8"))["files"]
    if expected != packaged:
        raise ValueError("installed customer source differs from this release; review upgrade before replacing it")


def stage_copy(source: Path, directory: Path) -> Path:
    """Copy a verified file beside its destination for one atomic replacement."""
    fd, name = tempfile.mkstemp(prefix=".wideband-fleetdeck-", dir=directory)
    staged = Path(name)
    try:
        with os.fdopen(fd, "wb") as output:
            input_fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(input_fd, "rb") as original:
                info = os.fstat(original.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError(f"Fleetdeck upgrade source is not a regular file: {source}")
                shutil.copyfileobj(original, output)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(staged, stat.S_IMODE(info.st_mode))
        return staged
    except Exception:
        staged.unlink(missing_ok=True)
        raise


def upgrade_delta(old: dict[str, str], new: dict[str, str]) -> tuple[set[str], set[str]]:
    """Allow reviewed code/assets changes, never removal or client-owned files."""
    changed = {name for name in old.keys() & new.keys() if old[name] != new[name]}
    added = set(new) - set(old)
    allowed_changes = UPGRADE_FILES | optional_assets(set(new))
    if set(old) - set(new) or changed - allowed_changes or added - (REQUIRED | optional_assets(set(new))):
        raise ValueError("Fleetdeck bundle differs outside reviewed managed files; review upgrade")
    return changed, added


def upgrade_parent(root: Path, name: str) -> Path:
    """Prepare a managed destination without traversing a client symlink."""
    parent = root
    for part in PurePosixPath(name).parts[:-1]:
        parent = parent / part
        if parent.is_symlink():
            raise ValueError(f"Fleetdeck managed parent is a symlink: {name}")
        if not parent.exists():
            parent.mkdir(mode=0o700)
        if not parent.is_dir():
            raise ValueError(f"Fleetdeck managed parent is not a directory: {name}")
    return parent


def upgrade_lock(installed: Path) -> int:
    path = installed.parent / f".{installed.name}.wideband-upgrade.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_nlink != 1 or info.st_mode & 0o077):
        os.close(fd)
        raise ValueError("Fleetdeck upgrade lock is unsafe")
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def upgrade(bundle: Path, installed: Path) -> Path | None:
    """Atomically install reviewed board files and preserve all client data."""
    lock_fd = upgrade_lock(installed)
    try:
        verify(bundle)
        old_hashes = verify_managed(installed)
        old_manifest = json.loads((installed / MANIFEST).read_text(encoding="utf-8"))
        new_manifest = json.loads((bundle / MANIFEST).read_text(encoding="utf-8"))
        if ({key: value for key, value in old_manifest.items() if key != "files"}
                != {key: value for key, value in new_manifest.items() if key != "files"}):
            raise ValueError("Fleetdeck package identity or source differs; review upgrade")
        new_hashes = new_manifest["files"]
        changed, added = upgrade_delta(old_hashes, new_hashes)
        if not changed and not added:
            return None
        for name in added:
            if (installed / name).exists() or (installed / name).is_symlink():
                raise ValueError(f"client file already uses a new managed path: {name}")

        backup = Path(tempfile.mkdtemp(prefix=f".{installed.name}-upgrade-backup-", dir=installed.parent))
        os.chmod(backup, 0o700)
        staged: list[Path] = []
        replaced = False
        try:
            for name in sorted(changed) + [MANIFEST]:
                parent = upgrade_parent(backup, name)
                prior = stage_copy(installed / name, parent)
                os.replace(prior, backup / name)
            for name in changed:
                if digest(backup / name) != old_hashes[name]:
                    raise ValueError(f"Fleetdeck managed file changed during backup: {name}")
            if (backup / MANIFEST).read_bytes() != (installed / MANIFEST).read_bytes():
                raise ValueError("Fleetdeck manifest changed during backup")
            to_write = sorted(changed | added)
            for name in to_write + [MANIFEST]:
                staged.append(stage_copy(bundle / name, upgrade_parent(installed, name)))
            if verify_managed(installed) != old_hashes:
                raise ValueError("Fleetdeck source changed during upgrade; review it before retrying")
            for name, staged_file in zip(to_write + [MANIFEST], staged):
                os.replace(staged_file, installed / name)
                replaced = True
            if verify_managed(installed) != new_hashes:
                raise ValueError("Fleetdeck upgrade did not verify")
            return backup
        except Exception as error:
            if replaced:
                try:
                    for name in sorted(added):
                        (installed / name).unlink(missing_ok=True)
                    for name in sorted(changed) + [MANIFEST]:
                        prior = stage_copy(backup / name, upgrade_parent(installed, name))
                        staged.append(prior)
                        os.replace(prior, installed / name)
                    if verify_managed(installed) != old_hashes:
                        raise ValueError("restored Fleetdeck source did not verify")
                except Exception as rollback_error:
                    raise RuntimeError(
                        f"Fleetdeck upgrade failed and rollback needs review; backup: {backup}"
                    ) from rollback_error
            raise ValueError(f"Fleetdeck upgrade stopped; previous source preserved: {error}") from error
        finally:
            for path in staged:
                path.unlink(missing_ok=True)
    finally:
        os.close(lock_fd)


def restore_previous(bundle: Path, installed: Path, backup: Path) -> None:
    """Restore the verified prior bundle if activation of the new board fails."""
    if (backup.parent != installed.parent
            or not backup.name.startswith(f".{installed.name}-upgrade-backup-")
            or backup.is_symlink() or not backup.is_dir()):
        raise ValueError("Fleetdeck portal backup path is unsafe")
    lock_fd = upgrade_lock(installed)
    try:
        verify(bundle)
        current_hashes = verify_managed(installed)
        packaged = json.loads((bundle / MANIFEST).read_text(encoding="utf-8"))
        if current_hashes != packaged["files"]:
            raise ValueError("Fleetdeck source changed after upgrade; preserve backup for review")
        backup_info = backup.stat()
        if backup_info.st_uid != os.getuid() or backup_info.st_mode & 0o077:
            raise ValueError("Fleetdeck portal backup permissions are unsafe")
        old_manifest_path = backup / MANIFEST
        if not regular_file(old_manifest_path):
            raise ValueError("Fleetdeck portal backup is incomplete")
        old_manifest = json.loads(old_manifest_path.read_text(encoding="utf-8"))
        old_hashes = old_manifest.get("files")
        if (not isinstance(old_hashes, dict)
                or {key: value for key, value in old_manifest.items() if key != "files"}
                != {key: value for key, value in packaged.items() if key != "files"}):
            raise ValueError("Fleetdeck portal backup does not match this upgrade")
        changed, added = upgrade_delta(old_hashes, current_hashes)
        if not changed and not added:
            raise ValueError("Fleetdeck portal backup has no upgrade to restore")
        for name in changed:
            item = backup / name
            if (not regular_file(item) or item.stat().st_uid != os.getuid()
                    or item.stat().st_nlink != 1 or digest(item) != old_hashes[name]):
                raise ValueError(f"Fleetdeck portal backup is unsafe: {name}")
        staged: list[Path] = []
        replaced = False
        try:
            for name in sorted(changed) + [MANIFEST]:
                staged.append(stage_copy(backup / name, upgrade_parent(installed, name)))
            for name in sorted(added):
                (installed / name).unlink()
                replaced = True
            for name, staged_file in zip(sorted(changed) + [MANIFEST], staged):
                os.replace(staged_file, installed / name)
                replaced = True
            if verify_managed(installed) != old_hashes:
                raise ValueError("restored Fleetdeck portal did not verify")
        except Exception as error:
            if replaced:
                try:
                    for name in sorted(changed | added) + [MANIFEST]:
                        latest = stage_copy(bundle / name, upgrade_parent(installed, name))
                        staged.append(latest)
                        os.replace(latest, installed / name)
                    if verify_managed(installed) != current_hashes:
                        raise ValueError("current Fleetdeck portal could not be restored")
                except Exception as repair_error:
                    raise RuntimeError(
                        f"Fleetdeck portal restore failed and needs review; backup: {backup}"
                    ) from repair_error
            raise ValueError(f"Fleetdeck portal restore stopped; backup preserved: {error}") from error
        finally:
            for path in staged:
                path.unlink(missing_ok=True)
    finally:
        os.close(lock_fd)


def main() -> int:
    try:
        if len(sys.argv) == 4 and sys.argv[1] == "build":
            build(Path(sys.argv[2]), Path(sys.argv[3]))
        elif len(sys.argv) == 3 and sys.argv[1] == "verify":
            verify(Path(sys.argv[2]))
        elif len(sys.argv) == 3 and sys.argv[1] == "verify-managed":
            verify_managed(Path(sys.argv[2]))
        elif len(sys.argv) == 4 and sys.argv[1] == "check-current":
            check_current(Path(sys.argv[2]), Path(sys.argv[3]))
        elif len(sys.argv) == 4 and sys.argv[1] == "upgrade":
            backup = upgrade(Path(sys.argv[2]), Path(sys.argv[3]))
            print("upgraded" if backup else "current")
            if backup:
                print(backup)
        elif len(sys.argv) == 5 and sys.argv[1] == "restore":
            restore_previous(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
            print("restored")
        else:
            print("usage: bundle-fleetdeck.py build SOURCE DEST | verify DEST | verify-managed INSTALLED | check-current BUNDLE INSTALLED | upgrade BUNDLE INSTALLED | restore BUNDLE INSTALLED BACKUP", file=sys.stderr)
            return 2
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, UnicodeError) as error:
        print(f"Fleetdeck bundle: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
