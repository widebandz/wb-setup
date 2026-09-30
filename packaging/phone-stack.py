#!/usr/bin/env python3
"""Install the VM-local services behind the real Fleetdeck phone board.

This is run only after the owner chat and first project have been established.
The customer board is installed by Fleetdeck itself; this reconciles its three
real companion surfaces without copying the operator Mac's private data.
"""

from __future__ import annotations

import importlib.util
import http.client
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
FD = HOME / "srv" / "fleetdeck"
GRAPH = HOME / "srv" / "glitch-cat-pilot"
GRAPH_BUNDLE = ROOT / "vendor" / "glitch-cat-pilot-bundle"
LA = HOME / "Library" / "LaunchAgents"
LOG_DIR = HOME / ".wideband" / "setup"
TS_APP = Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale")
TOKEN_PATH = HOME / ".wideband" / "fleetdeck" / "phone-access-token"
PATH_ENV = f"{HOME}/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def wait_port_free(port: int) -> None:
    for _ in range(120):
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                time.sleep(0.25)
                continue
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return
            except OSError:
                pass
        time.sleep(0.25)
    raise ValueError(f"local port {port} did not close")


def call(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=check,
                          timeout=45)


def graph_helper():
    path = ROOT / "packaging" / "glitch-cat-pilot.py"
    spec = importlib.util.spec_from_file_location("wideband_glitch_cat_pilot", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare_graph(label: str) -> str:
    helper = graph_helper()
    packaged = helper.verify(GRAPH_BUNDLE)
    if GRAPH.is_symlink():
        raise ValueError("graph location is a symlink")
    if not GRAPH.exists():
        helper.stage(GRAPH_BUNDLE, GRAPH)
    installed = helper.verify(GRAPH, staged=True)
    if installed != packaged:
        prior_job = LA / f"{label}.plist"
        if prior_job.exists() or prior_job.is_symlink():
            if prior_job.is_symlink():
                raise ValueError("existing Knowledge Graph LaunchAgent is a symlink")
            spec = plistlib.loads(prior_job.read_bytes())
            if (spec.get("Label") != label or spec.get("WorkingDirectory") != str(GRAPH)
                    or "engine/serve.mjs" not in spec.get("ProgramArguments", [])):
                raise ValueError("existing Knowledge Graph job has another owner")
            domain = f"gui/{os.getuid()}"
            if call("launchctl", "print", f"{domain}/{label}", check=False).returncode == 0:
                call("launchctl", "bootout", f"{domain}/{label}")
                for _ in range(40):
                    if call("launchctl", "print", f"{domain}/{label}", check=False).returncode != 0:
                        break
                    time.sleep(0.25)
                else:
                    raise ValueError("Knowledge Graph did not stop for source upgrade")
        wait_port_free(4180)
        helper.upgrade(GRAPH_BUNDLE, GRAPH)
        print("  + reviewed Knowledge Graph engine upgraded; private index preserved")
    helper.verify(GRAPH, staged=True)
    node = helper.node_path()
    if not (GRAPH / ".data" / "kg.db").is_file():
        helper.build(GRAPH)
    helper.preflight(GRAPH)
    if not (GRAPH / ".data" / "kg.db").is_file():
        raise ValueError("the VM-local graph index is missing")
    return node


def read_token() -> str:
    # The graph and terminal URLs never need this value. It is used only for a
    # local readiness request to the map and is never printed or persisted here.
    info = TOKEN_PATH.stat(follow_symlinks=False)
    if not TOKEN_PATH.is_file() or info.st_uid != os.getuid() or info.st_mode & 0o777 != 0o600:
        raise ValueError("private phone capability is missing or unsafe")
    value = TOKEN_PATH.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("private phone capability has an invalid format")
    return value


def tailscale_name() -> str:
    if not TS_APP.is_file():
        raise ValueError("Tailscale.app is required for the real phone stack")
    status = json.loads(call(str(TS_APP), "status", "--json").stdout)
    if status.get("BackendState") != "Running":
        raise ValueError("Tailscale is not connected")
    reported = status.get("Self", {}).get("DNSName", "")
    if not isinstance(reported, str):
        raise ValueError("Tailscale did not report this Mac's MagicDNS name")
    name = reported.rstrip(".").lower()
    if len(name) > 253 or not re.fullmatch(
            r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.){2,}ts\.net", name):
        raise ValueError("Tailscale did not report this Mac's MagicDNS name")
    return name


def ensure_serve(name: str, public_port: int, local_port: int, *,
                 previous_local_port: int | None = None) -> None:
    key = f"{name}:{public_port}"
    target = f"http://127.0.0.1:{local_port}"
    status = json.loads(call(str(TS_APP), "serve", "status", "--json").stdout or "{}")
    current = status.get("Web", {}).get(key, {}).get("Handlers", {}).get("/", {}).get("Proxy")
    previous = f"http://127.0.0.1:{previous_local_port}" if previous_local_port else None
    if current and current not in (target, previous):
        raise ValueError(f"Tailscale Serve :{public_port} has a different owner")
    if current != target:
        call(str(TS_APP), "serve", "--bg", f"--https={public_port}", target)
    status = json.loads(call(str(TS_APP), "serve", "status", "--json").stdout or "{}")
    actual = status.get("Web", {}).get(key, {}).get("Handlers", {}).get("/", {}).get("Proxy")
    if actual != target or status.get("TCP", {}).get(str(public_port), {}).get("HTTPS") is not True:
        raise ValueError(f"Tailscale Serve :{public_port} did not map to its local service")


def plist(label: str, argv: list[str], cwd: Path, env: dict[str, str]) -> bytes:
    data = {
        "Label": label, "ProgramArguments": argv, "WorkingDirectory": str(cwd),
        "EnvironmentVariables": {"PATH": PATH_ENV, **env},
        "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 10,
        "StandardOutPath": str(LOG_DIR / f"{label}.log"),
        "StandardErrorPath": str(LOG_DIR / f"{label}.log"),
    }
    return plistlib.dumps(data, sort_keys=True)


def ensure_job(label: str, content: bytes) -> None:
    LA.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(LOG_DIR, 0o700)
    dest = LA / f"{label}.plist"
    if dest.is_symlink():
        raise ValueError(f"LaunchAgent {label} is a symlink")
    old = dest.read_bytes() if dest.exists() else None
    if old and old != content:
        previous = plistlib.loads(old)
        wanted = plistlib.loads(content)
        prior_argv = previous.get("ProgramArguments", [])
        next_argv = wanted.get("ProgramArguments", [])
        if (previous.get("Label") != label
                or previous.get("WorkingDirectory") != wanted.get("WorkingDirectory")
                or prior_argv[1:] != next_argv[1:]):
            raise ValueError(f"LaunchAgent {label} has a different identity")
    if old != content:
        staged = dest.with_suffix(".plist.new")
        staged.write_bytes(content)
        os.chmod(staged, 0o600)
        os.replace(staged, dest)
    domain = f"gui/{os.getuid()}"
    loaded = call("launchctl", "print", f"{domain}/{label}", check=False).returncode == 0
    if loaded and old != content:
        call("launchctl", "bootout", f"{domain}/{label}")
        for _ in range(30):
            if call("launchctl", "print", f"{domain}/{label}", check=False).returncode != 0:
                break
            time.sleep(0.2)
        else:
            raise ValueError(f"LaunchAgent {label} did not unload")
        loaded = False
    if not loaded:
        call("launchctl", "bootstrap", domain, str(dest))
    if call("launchctl", "print", f"{domain}/{label}", check=False).returncode != 0:
        raise ValueError(f"LaunchAgent {label} is not loaded")


def get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "Wideband-Setup/phone-stack"})
    with urllib.request.urlopen(request, timeout=3) as response:
        if response.status != 200:
            raise ValueError("service did not answer")
        raw = response.read(2 * 1024 * 1024)
    return json.loads(raw)


def wait_ready(label: str, predicate) -> None:
    for _ in range(40):
        try:
            if predicate():
                print(f"  ✓ {label} is serving VM-local data")
                return
        except (OSError, ValueError, urllib.error.URLError, KeyError, TypeError):
            pass
        time.sleep(0.25)
    raise ValueError(f"{label} did not answer its data probe")


def register_service(service: dict) -> None:
    path = FD / "services.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError("Fleetdeck service registry is missing or unsafe")
    data = json.loads(path.read_text(encoding="utf-8"))
    services = data.get("services")
    if not isinstance(services, list):
        raise ValueError("Fleetdeck service registry has no services list")
    groups = data.get("groups")
    if not isinstance(groups, list):
        raise ValueError("Fleetdeck service registry has no groups list")
    group_added = not any(isinstance(item, dict) and item.get("id") == service["group"] for item in groups)
    if group_added:
        groups.insert(0, {"id": service["group"], "label": service["group"]})
    found = [item for item in services if isinstance(item, dict) and item.get("id") == service["id"]]
    changed = group_added
    if found:
        if len(found) != 1 or found[0].get("source") != "wideband-phone-stack":
            raise ValueError(f"Fleetdeck service ID {service['id']} belongs to another entry")
        if found[0].get("port") != service["port"]:
            # The first real-stack pilot linked the graph engine directly on
            # 4180. Its managed tile must follow the new owner-gated front.
            if (service["id"], found[0].get("port"), service["port"]) != ("graph", 4180, 4181):
                raise ValueError(f"Fleetdeck service ID {service['id']} belongs to another entry")
            found[0]["port"] = 4181
            changed = True
        if not changed:
            return
    else:
        services.append({**service, "source": "wideband-phone-stack"})
    temp = path.with_name(".services.json.wideband-new")
    if temp.exists() or temp.is_symlink():
        raise ValueError("Fleetdeck service registry staging path is occupied")
    with temp.open("x", encoding="utf-8") as output:
        json.dump(data, output, indent=2, ensure_ascii=False)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def refresh_graph_index(label: str, content: bytes) -> None:
    """Reindex after the real services/routes exist, retaining the old DB on failure."""
    manifest = GRAPH_BUNDLE / ".wideband-glitch-cat-pilot.json"
    registry = FD / "services.json"
    fingerprint = hashlib.sha256(b"phone-stack-v1\0" + manifest.read_bytes()
                                 + b"\0" + registry.read_bytes()).hexdigest()
    marker = LOG_DIR / "phone-graph-index-fingerprint"
    if marker.is_file() and marker.read_text(encoding="ascii").strip() == fingerprint:
        return
    domain = f"gui/{os.getuid()}"
    if call("launchctl", "print", f"{domain}/{label}", check=False).returncode == 0:
        call("launchctl", "bootout", f"{domain}/{label}")
        for _ in range(120):
            if call("launchctl", "print", f"{domain}/{label}", check=False).returncode != 0:
                break
            time.sleep(0.25)
        else:
            raise ValueError("Knowledge Graph did not unload for index refresh")
    wait_port_free(4180)
    failure = None
    try:
        graph_helper().build(GRAPH)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        failure = error
    finally:
        ensure_job(label, content)
    if failure:
        raise failure
    staged = marker.with_suffix(".new")
    staged.write_text(fingerprint + "\n", encoding="ascii")
    os.chmod(staged, 0o600)
    os.replace(staged, marker)


def run() -> None:
    config = json.loads((FD / "config.json").read_text(encoding="utf-8"))
    prefix = config.get("label_prefix")
    if not isinstance(prefix, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9.-]{1,99}", prefix):
        raise ValueError("Fleetdeck LaunchAgent prefix is invalid")
    if not (FD / ".wideband-fleetdeck-bundle.json").is_file():
        raise ValueError("the real Fleetdeck bundle is required for the full phone stack")
    name = tailscale_name()
    capability = read_token()
    graph_label = prefix + ".glitch-cat"
    graph_proxy_label = prefix + ".fleetdeck-graph"
    node = prepare_graph(graph_label)
    python = str(Path(sys.executable).resolve())
    map_label = prefix + ".fleetdeck-map"
    chat_label = prefix + ".fleetdeck-chat"
    ensure_job(map_label, plist(map_label, [python, "-m", "customer_fleet_map.server"],
                                ROOT / "packaging", {
        "FLEETDECK_FLEET_MAP_BIND": "127.0.0.1", "FLEETDECK_FLEET_MAP_PORT": "18790",
        "FLEETDECK_FLEET_HOST_ID": name.split(".", 1)[0],
        "FLEETDECK_BOARD_ORIGIN": f"https://{name}:8790",
    }))
    graph_plist = plist(graph_label, [node, "engine/serve.mjs", "--port", "4180"], GRAPH, {
        "GLITCHCAT_PACK": "wideband-pilot", "GLITCHCAT_DB": str(GRAPH / ".data" / "kg.db"),
    })
    ensure_job(graph_label, graph_plist)
    ensure_job(graph_proxy_label, plist(
        graph_proxy_label, [python, str(ROOT / "packaging" / "customer_graph_proxy.py")],
        ROOT / "packaging", {}))
    def map_ready() -> bool:
        data = get_json(f"http://127.0.0.1:18790/p/{capability}/api/fleet-map")
        return (data.get("schema_version") == "agent-fleet.snapshot.v1"
                and any(isinstance(item, dict) and item.get("type") == "session"
                        and item.get("observed") is True for item in data.get("nodes", [])))
    def graph_ready() -> bool:
        stats = get_json("http://127.0.0.1:4180/api/stats")
        surface = get_json("http://127.0.0.1:4180/api/graph?lens=surface")
        return (type(stats.get("nodes")) is int and stats["nodes"] > 0
                and isinstance(stats.get("run"), dict) and bool(stats["run"].get("at"))
                and isinstance(surface.get("nodes"), list) and bool(surface["nodes"])
                and isinstance(surface.get("edges"), list) and bool(surface["edges"]))
    def graph_proxy_ready() -> bool:
        try:
            urllib.request.urlopen("http://127.0.0.1:4181/api/stats", timeout=3)
        except urllib.error.HTTPError as error:
            if error.code != 403:
                return False
        else:
            return False
        connection = http.client.HTTPConnection("127.0.0.1", 4181, timeout=3)
        try:
            connection.request("GET", f"/p/{capability}/graph")
            response = connection.getresponse()
            cookie = response.getheader("Set-Cookie", "").split(";", 1)[0]
            if response.status != 303 or response.getheader("Location") != "/" \
                    or not cookie.startswith("wb_fleetdeck_session="):
                return False
            response.read()
            connection.request("GET", "/api/stats", headers={"Cookie": cookie})
            response = connection.getresponse()
            stats = json.loads(response.read()) if response.status == 200 else {}
        finally:
            connection.close()
        return type(stats.get("nodes")) is int and stats["nodes"] > 0
    wait_ready("Live Terminal Network", map_ready)
    wait_ready("Knowledge Graph", graph_ready)
    wait_ready("owner-gated Knowledge Graph", graph_proxy_ready)
    ensure_serve(name, 18970, 18790)
    # The first real-stack pilot routed :8792 straight to the graph engine.
    # Move only that exact managed mapping behind the new owner gate.
    ensure_serve(name, 8792, 4181, previous_local_port=4180)

    # Fleetdeck renders its network button from this safe origin and reads the
    # owner capability itself. No raw capability goes into config or launchd.
    portal_label = prefix + ".fleetdeck-portal"
    portal_plist = LA / f"{portal_label}.plist"
    if portal_plist.is_symlink() or not portal_plist.is_file():
        raise ValueError("Fleetdeck portal LaunchAgent is missing")
    portal_spec = plistlib.loads(portal_plist.read_bytes())
    if portal_spec.get("Label") != portal_label or str(FD / "portal_server.py") not in portal_spec.get("ProgramArguments", []):
        raise ValueError("Fleetdeck portal LaunchAgent has an unexpected program")
    configured_host = config.get("machine") or ""
    if configured_host and configured_host.lower().rstrip(".") != name:
        raise ValueError("Fleetdeck config names a different phone host")
    portal_spec.setdefault("EnvironmentVariables", {})["FLEETDECK_HOST"] = name
    portal_spec.setdefault("EnvironmentVariables", {})["FLEETDECK_MAP_ORIGIN"] = f"https://{name}:18970"
    ensure_job(portal_label, plistlib.dumps(portal_spec, sort_keys=True))

    # The real chat server is a separate, cookie-gated writable ttyd proxy.
    # It is activated only after the first owner-to-agent reply, which is the
    # point at which this scoped phone install becomes available.
    chat = FD / "chat_server.py"
    if not chat.is_file() or "FLEETDECK_CUSTOMER_TERMINALS" not in chat.read_text(encoding="utf-8"):
        raise ValueError("reviewed customer tmux chat server is missing")
    ensure_job(chat_label, plist(chat_label, [python, str(chat)], FD, {
        "PORT": "8783", "TTYD_PORT": "8784", "BIND": "127.0.0.1",
        "FLEETDECK_CUSTOMER_TERMINALS": "1",
        "FLEETDECK_HOST": name,
    }))
    def chat_ready() -> bool:
        try:
            urllib.request.urlopen("http://127.0.0.1:8783/", timeout=3)
        except urllib.error.HTTPError as error:
            if error.code != 403:
                return False
        else:
            return False
        connection = http.client.HTTPConnection("127.0.0.1", 8783, timeout=3)
        try:
            connection.request("GET", f"/p/{capability}/chat")
            response = connection.getresponse()
            cookie = response.getheader("Set-Cookie", "").split(";", 1)[0]
            if response.status != 303 or not cookie.startswith("wb_fleetdeck_session="):
                return False
            response.read()
            connection.request("GET", "/healthz", headers={"Cookie": cookie})
            response = connection.getresponse()
            status = json.loads(response.read()) if response.status == 200 else {}
        finally:
            connection.close()
        return status.get("ok") is True and status.get("ttyd") is True
    wait_ready("tmux fleet terminals", chat_ready)
    ensure_serve(name, 8783, 8783)

    register_service({"id": "chat", "group": "fleet", "port": 8783,
                      "icon": "chat", "name": "Live terminals",
                      "blurb": "Real tmux sessions on this Mac"})
    register_service({"id": "graph", "group": "fleet", "port": 4181,
                      "icon": "nodes", "name": "Knowledge Graph",
                      "blurb": "Indexed graph of this Mac's projects and operator plane"})
    refresh_graph_index(graph_label, graph_plist)
    wait_ready("refreshed Knowledge Graph", graph_ready)
    wait_ready("refreshed owner-gated Knowledge Graph", graph_proxy_ready)
    print("  ✓ real Fleetdeck companion services have private Tailscale Serve routes")


if __name__ == "__main__":
    try:
        run()
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired,
            json.JSONDecodeError) as error:
        print(f"  ✗ real Fleetdeck phone stack: {error}", file=sys.stderr)
        raise SystemExit(1)
