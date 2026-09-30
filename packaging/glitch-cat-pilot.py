#!/usr/bin/env python3
"""Stage a private, local-corpus Glitch Cat pilot without host packs or data.

This helper is deliberately separate from the customer installer. It never
changes Fleetdeck, launchd, Tailscale, or an existing graph installation.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile


MANIFEST = ".wideband-glitch-cat-pilot.json"
PACK = "wideband-pilot"
PORT = 4180
TOOLCHAIN_RESOLVER = Path(__file__).resolve().parents[1] / "lib" / "toolchain-path"
REQUIRED = {
    "package.json", "package-lock.json", "engine/cli.mjs",
    "engine/serve.mjs", "engine/paths.mjs", "engine/schema.mjs",
    "engine/roots.mjs", "engine/conventions.mjs", "engine/types.mjs",
}
ICON_NAMES = {
    f"engine/icons/{name}-{size}.png"
    for name in ("graph", "health") for size in ("180", "192", "512")
}
TAILNET_URL = re.compile(r"https?://([A-Za-z0-9-]+)\.[A-Za-z0-9.-]+\.ts\.net(?::\d+)?")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
HOME_PATH = re.compile(r"/Users/[^/\s'\"`]+")
PRIVATE_OUTPUT = (
    re.compile(rb"[A-Za-z0-9.-]+\.ts\.net"),
    re.compile(rb"/Users/(?!example(?:/|\b))[^/\s]+"),
    re.compile(rb"[A-Za-z0-9._%+-]+@(?!example\.test)[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
)
DEFAULT_LENS_SOURCE = "let lens='governance',focus=null,depth=1,defs={},hideIso=true;"
DEFAULT_LENS_PILOT = "let lens='surface',focus=null,depth=1,defs={},hideIso=true;"
GRAPH_STYLE_MARKER = '</style></head><body><div id="wrap">'
GRAPH_STAGE_MARKER = '<div id="stage">\n  <canvas id="c"></canvas>'
GRAPH_SCRIPT_MARKER = "\n(async()=>{"
GRAPH_SERVER_MARKER = ("createServer((req, res) => {\n"
                       "  const url = new URL(req.url, `http://${req.headers.host}`)\n"
                       "  try {")
GRAPH_SERVER_GUARD = ("createServer((req, res) => {\n"
                      "  // A foreign Host can resolve to loopback through DNS rebinding.\n"
                      "  // This private engine is read only, but its graph is client data.\n"
                      "  if (req.headers.host !== `127.0.0.1:${PORT}`\n"
                      "      && req.headers.host !== `localhost:${PORT}`) {\n"
                      "    res.writeHead(403, { 'content-type': 'text/plain; charset=utf-8' })\n"
                      "    return res.end('forbidden\\n')\n"
                      "  }\n"
                      "  try {\n"
                      "    const url = new URL(req.url, `http://127.0.0.1:${PORT}`)")
MOBILE_GRAPH_STYLE = """
#mobile-lenses,#mobile-close{display:none}
@media(max-width:720px){
  #wrap{display:block;height:100dvh}
  #side{position:absolute;inset:0 auto 0 0;width:min(88vw,340px);height:100dvh;
    z-index:30;transform:translateX(-105%);transition:transform .18s ease;
    box-shadow:12px 0 32px rgba(0,0,0,.6);padding-top:calc(14px + env(safe-area-inset-top))}
  #side.open{transform:translateX(0)}
  #stage{width:100%;height:100dvh}
  #mobile-lenses,#mobile-close{display:block;border:1px solid var(--teal);
    background:var(--panel);color:var(--teal);border-radius:6px;
    padding:9px 11px;font:inherit;cursor:pointer}
  #mobile-lenses{position:absolute;z-index:15;top:calc(10px + env(safe-area-inset-top));left:10px}
  #mobile-close{float:right;margin:0 0 8px 8px}
  #hud{left:10px;right:10px;bottom:calc(10px + env(safe-area-inset-bottom));
    background:rgba(17,24,32,.9);border:1px solid var(--line);border-radius:6px;padding:7px}
  #detail{left:10px;right:10px;top:auto;bottom:calc(55px + env(safe-area-inset-bottom));
    width:auto;max-height:55dvh}
  canvas{touch-action:none}
}
"""
MOBILE_GRAPH_SCRIPT = """
const mobileLenses=document.getElementById('mobile-lenses');
const graphSide=document.getElementById('side');
function graphMenu(open){graphSide.classList.toggle('open',open);mobileLenses.setAttribute('aria-expanded',String(open))}
mobileLenses.onclick=()=>graphMenu(!graphSide.classList.contains('open'));
document.getElementById('mobile-close').onclick=()=>graphMenu(false);
document.getElementById('lenses').addEventListener('click',e=>{
  const b=e.target.closest('.lens');if(!b)return;
  mobileLenses.textContent='☷ '+b.childNodes[0].textContent.trim();graphMenu(false);
});
let graphTouch=null;
C.addEventListener('touchstart',e=>{
  if(e.touches.length===1){const t=e.touches[0];graphTouch={mode:'pan',x:t.clientX,y:t.clientY,cx:cam.x,cy:cam.y}}
  else if(e.touches.length===2){const a=e.touches[0],b=e.touches[1];
    graphTouch={mode:'zoom',distance:Math.hypot(a.clientX-b.clientX,a.clientY-b.clientY),z:cam.z}}
},{passive:true});
C.addEventListener('touchmove',e=>{
  if(!graphTouch)return;e.preventDefault();
  if(graphTouch.mode==='pan'&&e.touches.length===1){const t=e.touches[0];
    cam.x=graphTouch.cx+t.clientX-graphTouch.x;cam.y=graphTouch.cy+t.clientY-graphTouch.y}
  else if(graphTouch.mode==='zoom'&&e.touches.length===2){const a=e.touches[0],b=e.touches[1];
    const distance=Math.hypot(a.clientX-b.clientX,a.clientY-b.clientY);
    cam.z=Math.max(.25,Math.min(3,graphTouch.z*distance/Math.max(1,graphTouch.distance)))}
},{passive:false});
C.addEventListener('touchend',e=>{if(!e.touches.length)graphTouch=null},{passive:true});
"""
TAILSCALE_SOURCE = "for (const line of sh('tailscale', ['serve', 'status']).split('\\n')) {"
TAILSCALE_PILOT = ("const serveStatus = sh('tailscale', ['serve', 'status'])\n"
                   "    || sh('/Applications/Tailscale.app/Contents/MacOS/Tailscale', ['serve', 'status'])\n"
                   "  for (const line of serveStatus.split('\\n')) {")


def regular(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_relative(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name and not path.is_absolute() and
                all(part not in ("", ".", "..") for part in name.split("/")) and
                all(ord(c) >= 32 and ord(c) != 127 for c in name))


def source_files(source: Path) -> set[str]:
    source = source.resolve(strict=True)
    root = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "--show-toplevel"], text=True
    ).strip()
    if Path(root).resolve() != source:
        raise ValueError("Glitch Cat source must be its repository root")
    tracked = {
        os.fsdecode(raw) for raw in subprocess.check_output(
            ["git", "-C", str(source), "ls-files", "--cached", "-z"]
        ).split(b"\0") if raw
    }
    allowed = {name for name in tracked if
               (name.startswith("engine/") and name.count("/") == 1 and
                name.endswith(".mjs") and not name.endswith(".test.mjs")) or
               name in ICON_NAMES or name in {"package.json", "package-lock.json"}}
    if not REQUIRED.issubset(allowed) or not ICON_NAMES.issubset(allowed):
        raise ValueError("Glitch Cat source lacks required tracked engine files")
    for name in allowed:
        if not safe_relative(name) or not regular(source / name):
            raise ValueError(f"unsafe or missing tracked engine file: {name}")
    pkg = json.loads((source / "package.json").read_text(encoding="utf-8"))
    if pkg.get("scripts", {}).get("graph") != "node engine/cli.mjs" or \
            pkg.get("scripts", {}).get("serve") != "node engine/serve.mjs":
        raise ValueError("unrecognized Glitch Cat package scripts")
    return allowed


def sanitized_bytes(name: str, data: bytes, host_aliases: set[str] | None = None) -> bytes:
    if name.endswith(".png"):
        return data
    text = data.decode("utf-8")
    text = TAILNET_URL.sub("/", text)
    text = EMAIL.sub(lambda m: "account-" + hashlib.sha256(m.group().encode()).hexdigest()[:8] +
                     "@example.test", text)
    text = HOME_PATH.sub("/Users/example", text)
    text = re.sub(r"\bcom\.[a-z0-9_-]+\.g2voice\b", "com.example.voice", text)
    text = re.sub(r"\b[a-z0-9-]+\.io\b", "reference.example", text)
    text = re.sub(r"\bflow-[a-z0-9-]+-ai\b", "example-codebase", text)
    for alias in host_aliases or ():
        text = re.sub(rf"\b{re.escape(alias)}\b", "agent-mac", text)
    if name == "engine/serve.mjs":
        if text.count(DEFAULT_LENS_SOURCE) != 1:
            raise ValueError("Glitch Cat default lens source changed; review the viewer")
        text = text.replace(DEFAULT_LENS_SOURCE, DEFAULT_LENS_PILOT)
        for marker in (GRAPH_STYLE_MARKER, GRAPH_STAGE_MARKER,
                       GRAPH_SCRIPT_MARKER, '<div id="side">'):
            if text.count(marker) != 1:
                raise ValueError("Glitch Cat graph viewer changed; review the mobile layout")
        text = text.replace(GRAPH_STYLE_MARKER, MOBILE_GRAPH_STYLE + GRAPH_STYLE_MARKER, 1)
        text = text.replace(GRAPH_STAGE_MARKER,
                            '<div id="stage">\n  <button id="mobile-lenses" type="button" '
                            'aria-controls="side" aria-expanded="false">☷ Surfaces</button>\n'
                            '  <canvas id="c"></canvas>', 1)
        text = text.replace('<div id="side">', '<div id="side">\n  <button id="mobile-close" '
                            'type="button">Close</button>', 1)
        text = text.replace(GRAPH_SCRIPT_MARKER, "\n" + MOBILE_GRAPH_SCRIPT + GRAPH_SCRIPT_MARKER, 1)
        if text.count(GRAPH_SERVER_MARKER) != 1:
            raise ValueError("Glitch Cat graph server changed; review the Host boundary")
        text = text.replace(GRAPH_SERVER_MARKER, GRAPH_SERVER_GUARD, 1)
    if name == "engine/cli.mjs":
        if text.count(TAILSCALE_SOURCE) != 1:
            raise ValueError("Glitch Cat Tailscale scan changed; review the reader")
        text = text.replace(TAILSCALE_SOURCE, TAILSCALE_PILOT)
    result = text.encode("utf-8")
    if any(pattern.search(result) for pattern in PRIVATE_OUTPUT):
        raise ValueError(f"host identifier remains in generic engine: {name}")
    return result


def bundle(source: Path, target: Path) -> None:
    names = source_files(source)
    host_aliases = set()
    for name in names:
        if name.endswith(".mjs"):
            host_aliases.update(TAILNET_URL.findall((source / name).read_text(encoding="utf-8")))
    target.mkdir(mode=0o700, parents=True, exist_ok=False)
    try:
        hashes = {}
        for name in sorted(names):
            dest = target / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(sanitized_bytes(name, (source / name).read_bytes(), host_aliases))
            hashes[name] = sha(dest)
        (target / MANIFEST).write_text(json.dumps({
            "schema_version": 1,
            "source": "tracked-generic-engine-sanitized",
            "files": hashes,
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        verify(target)
    except Exception:
        shutil.rmtree(target)
        raise


def verify(root: Path, *, staged: bool = False) -> dict[str, str]:
    if root.is_symlink() or not root.is_dir() or not regular(root / MANIFEST):
        raise ValueError("Glitch Cat pilot bundle is missing or unsafe")
    meta = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    hashes = meta.get("files")
    if meta.get("schema_version") != 1 or meta.get("source") != "tracked-generic-engine-sanitized" or \
            not isinstance(hashes, dict) or not REQUIRED.issubset(hashes) or \
            not ICON_NAMES.issubset(hashes):
        raise ValueError("unrecognized Glitch Cat pilot manifest")
    for name, expected in hashes.items():
        if not safe_relative(name) or not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError("unsafe pilot manifest entry")
        path = root / name
        if not regular(path) or sha(path) != expected:
            raise ValueError(f"Glitch Cat pilot file changed: {name}")
    for path in root.rglob("*"):
        rel = path.relative_to(root).as_posix()
        if staged and rel.startswith("node_modules/"):
            # npm ci creates package-owned links under .bin. The lockfile and
            # ignored scripts constrain installation; these are not payload.
            continue
        if path.is_symlink():
            raise ValueError(f"symlink in Glitch Cat pilot: {rel}")
        if path.is_file() and rel not in hashes and rel != MANIFEST:
            if not staged or not (rel.startswith(f"packs/{PACK}/") or
                                   rel.startswith(".data/") or
                                   rel.startswith("node_modules/")):
                raise ValueError(f"unexpected Glitch Cat pilot file: {rel}")
    return hashes


ROOTS = """version: 1
roots:
  - name: wb-setup
    main: true
    path: ~/srv/wb-setup
    kind: walk
    governance: false
    file_nodes: all
  - name: first-project
    path: ~/wideband/first-project
    kind: walk
    prefix: '@first-project'
    governance: false
    file_nodes: all
"""

CONVENTIONS = """version: 1
zones:
  - { prefix: 'imessage/', zone: messaging }
  - { prefix: 'first_goal/', zone: first-job }
  - { prefix: 'packaging/', zone: installer }
  - { prefix: 'installer/', zone: installer-ui }
  - { prefix: 'tests/', zone: tests }
  - { prefix: 'public/', zone: first-project }
default_zone: setup
doc_dirs: [skills, templates]
plane:
  launchd_prefix: '(ai|com)\\.wideband\\.'
"""


def stage(source: Path, target: Path) -> None:
    verify(source)
    if target.exists() or target.is_symlink():
        raise ValueError("pilot target exists; existing graphs and client data are preserved")
    target.mkdir(parents=True, mode=0o700)
    try:
        for name in json.loads((source / MANIFEST).read_text())["files"]:
            dest = target / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, dest)
        shutil.copy2(source / MANIFEST, target / MANIFEST)
        pack = target / "packs" / PACK
        pack.mkdir(parents=True)
        (pack / "roots.yaml").write_text(ROOTS, encoding="utf-8")
        (pack / "conventions.yaml").write_text(CONVENTIONS, encoding="utf-8")
        (target / ".data").mkdir(mode=0o700)
        os.chmod(target, 0o700)
        verify(target, staged=True)
    except Exception:
        shutil.rmtree(target)
        raise


def port_free(port: int) -> None:
    # A successful TCP handshake proves a listener is still accepting clients.
    # A plain bind alone can fail for a short time after launchd stops the
    # viewer because an old connection remains in TIME_WAIT.
    if port:
        with socket.socket() as probe:
            probe.settimeout(0.25)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise ValueError(f"stop the graph viewer on port {port} before upgrading or rebuilding")
    with socket.socket() as sock:
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
        except OSError as error:
            raise ValueError(f"stop the graph viewer on port {port} before upgrading or rebuilding") from error


def upgrade(source: Path, target: Path, *, port: int = PORT) -> Path:
    """Swap reviewed engine bytes; retain client pack, index, and dependencies."""
    new_files = verify(source)
    old_files = verify(target, staged=True)
    if stat.S_IMODE(target.stat().st_mode) != 0o700:
        raise ValueError("pilot target must be mode 0700")
    if any(old_files.get(name) != new_files.get(name)
           for name in ("package.json", "package-lock.json")):
        raise ValueError("dependency manifest changed; review and stage a fresh pilot")
    port_free(port)
    with tempfile.TemporaryDirectory(prefix=".glitch-cat-next-", dir=target.parent) as temp:
        next_root = Path(temp) / "next"
        shutil.copytree(target, next_root, symlinks=True)
        for name in old_files:
            (next_root / name).unlink()
        for name in new_files:
            dest = next_root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name, dest)
        shutil.copy2(source / MANIFEST, next_root / MANIFEST)
        verify(next_root, staged=True)
        backup = target.parent / f".{target.name}.backup-{secrets.token_hex(5)}"
        os.replace(target, backup)
        try:
            os.replace(next_root, target)
        except Exception:
            os.replace(backup, target)
            raise
        return backup


def runtime_env(root: Path, node: str) -> dict[str, str]:
    return {**os.environ, "GLITCHCAT_PACK": PACK,
            "GLITCHCAT_DB": str(root / ".data" / "kg.db"),
            "PATH": f"{Path(node).parent}:/usr/bin:/bin:/usr/sbin:/sbin"}


def tool_path(name: str) -> str:
    """Resolve only a validated payload or explicitly approved legacy tool."""
    if name not in ("node", "npm"):
        raise ValueError("unreviewed graph tool")
    try:
        result = subprocess.run([str(TOOLCHAIN_RESOLVER), name],
                                capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(f"verified {name} is unavailable") from error
    path = Path(result.stdout.strip())
    if (result.returncode or not path.is_absolute() or path.name != name
            or not path.is_file()):
        raise ValueError(f"verified {name} is unavailable")
    return str(path)


def node_path() -> str:
    node = tool_path("node")
    version = subprocess.check_output([node, "--version"], text=True).strip()
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", version)
    if not match or (int(match[1]), int(match[2])) < (22, 5):
        raise ValueError("Node 22.5 or newer is required")
    return node


def preflight(root: Path, *, need_db: bool = False, port: int = PORT) -> str:
    verify(root, staged=True)
    if stat.S_IMODE(root.stat().st_mode) != 0o700 or \
            stat.S_IMODE((root / ".data").stat().st_mode) != 0o700:
        raise ValueError("pilot source and database directories must be mode 0700")
    pack = root / "packs" / PACK
    if (pack / "roots.yaml").read_text(encoding="utf-8") != ROOTS or \
            (pack / "conventions.yaml").read_text(encoding="utf-8") != CONVENTIONS:
        raise ValueError("pilot corpus declaration changed; review it before building")
    home = Path.home()
    for rel in ("srv/wb-setup", "wideband/first-project"):
        path = home / rel
        if path.is_symlink() or not path.is_dir():
            raise ValueError(f"local graph root is missing or unsafe: ~/{rel}")
    node = node_path()
    if need_db and not regular(root / ".data" / "kg.db"):
        raise ValueError("graph index is missing; build it first")
    if need_db:
        port_free(port)
    return node


def build(root: Path, *, port: int = PORT) -> None:
    node = preflight(root)
    port_free(port)
    npm = tool_path("npm")
    if Path(npm).parent != Path(node).parent:
        raise ValueError("verified Node and npm are from different installations")
    env = runtime_env(root, node)
    subprocess.run([npm, "ci", "--omit=dev", "--ignore-scripts", "--no-audit", "--no-fund"],
                   cwd=root, env=env, check=True)
    data_dir = root / ".data"
    with tempfile.TemporaryDirectory(prefix="build-", dir=data_dir) as temp:
        db_path = Path(temp) / "kg.db"
        env["GLITCHCAT_DB"] = str(db_path)
        subprocess.run([node, "engine/cli.mjs", "build"], cwd=root, env=env, check=True)
        subprocess.run([node, "engine/cli.mjs", "status"], cwd=root, env=env, check=True)
        with sqlite3.connect(db_path) as db:
            count = db.execute("SELECT count(*) FROM node").fetchone()[0]
            if count < 2 or db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("graph build did not produce a valid local index")
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        os.chmod(db_path, 0o600)
        os.replace(db_path, data_dir / "kg.db")


def serve(root: Path, port: int = PORT) -> None:
    node = preflight(root, need_db=True, port=port)
    env = runtime_env(root, node)
    subprocess.run([node, "engine/serve.mjs", "--port", str(port)],
                   cwd=root, env=env, check=True)


def main(argv: list[str]) -> int:
    try:
        if len(argv) == 4 and argv[1] == "bundle":
            bundle(Path(argv[2]), Path(argv[3]))
        elif len(argv) == 3 and argv[1] == "verify":
            verify(Path(argv[2]))
        elif len(argv) == 4 and argv[1] == "stage":
            stage(Path(argv[2]), Path(argv[3]))
        elif len(argv) in (4, 5) and argv[1] == "upgrade":
            backup = upgrade(Path(argv[2]), Path(argv[3]),
                             port=int(argv[4]) if len(argv) == 5 else PORT)
            print(f"pilot engine upgraded; previous installation retained at {backup}")
        elif len(argv) == 3 and argv[1] == "preflight":
            preflight(Path(argv[2]))
        elif len(argv) in (3, 4) and argv[1] == "build":
            build(Path(argv[2]), port=int(argv[3]) if len(argv) == 4 else PORT)
        elif len(argv) in (3, 4) and argv[1] == "serve":
            serve(Path(argv[2]), int(argv[3]) if len(argv) == 4 else PORT)
        else:
            print("usage: glitch-cat-pilot.py bundle SOURCE TARGET | verify BUNDLE | "
                  "stage BUNDLE TARGET | upgrade BUNDLE TARGET [PORT] | "
                  "preflight TARGET | build TARGET [PORT] | serve TARGET [PORT]",
                  file=sys.stderr)
            return 2
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        print(f"Glitch Cat pilot: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
