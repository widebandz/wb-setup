#!/usr/bin/env python3
"""Prepare only the first capability selected in Wideband Setup."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
from pathlib import Path
import plistlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request


GOALS = {"research", "website", "proposal"}
SERVICE_ID = "first-project"
LABEL = "ai.wideband.first-project"
PORTS = range(4173, 4200)
HOME = Path.home()
STATE = HOME / ".wideband" / "setup" / "state.json"
GOAL_DIR = HOME / ".wideband" / "first-goal"
STATUS = GOAL_DIR / "status.json"
PROJECT = HOME / "wideband" / "first-project"
PLIST = HOME / "Library" / "LaunchAgents" / f"{LABEL}.plist"
SCRIPT = Path(__file__).with_name("site_server.py")
BRAND_ICON = Path(__file__).resolve().parents[1] / "installer" / "wideband-mark.png"


def private_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def identity() -> tuple[str, str, str]:
    state = json.loads(STATE.read_text(encoding="utf-8"))
    metadata = state.get("metadata", {})
    os_name = metadata.get("os_name")
    agent_name = metadata.get("agent_name")
    goal = metadata.get("first_goal")
    if not isinstance(os_name, str) or not os_name.strip() or len(os_name) > 80:
        raise ValueError("save an OS name in Wideband Setup first")
    if not isinstance(agent_name, str) or not agent_name.strip() or len(agent_name) > 80:
        raise ValueError("save a head-agent name in Wideband Setup first")
    if goal not in GOALS:
        raise ValueError("choose Research, Website, or Proposal in Wideband Setup first")
    return os_name.strip(), agent_name.strip(), goal


def read_status() -> dict:
    try:
        value = json.loads(STATUS.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def selected_port(previous: dict) -> int:
    prior = previous.get("port")
    if isinstance(prior, int) and prior in PORTS:
        return prior
    for port in PORTS:
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("no free preview port from 4173 to 4199")


def write_generated(path: Path, content: str, previous_hash: str | None = None) -> str | None:
    """Refresh our starter only when it still matches our last generated copy."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or not path.is_file():
            return None
        current_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        wanted_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if current_hash == wanted_hash:
            return wanted_hash
        if current_hash != previous_hash:
            return None
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o644)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def site_content(os_name: str, agent_name: str) -> str:
    title = html.escape(os_name)
    agent = html.escape(agent_name)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#111923"><title>{title} · First project</title>
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-title" content="{title}">
<link rel="apple-touch-icon" href="/icons/apple-touch-icon.png"><link rel="manifest" href="/manifest.webmanifest">
<style>body{{margin:0;background:#111923;color:#eaf8fa;font:16px/1.55 system-ui,sans-serif}}
main{{max-width:680px;margin:12vh auto;padding:32px}}small{{color:#67e8f9;letter-spacing:.18em;text-transform:uppercase}}
h1{{font-size:clamp(2.5rem,8vw,5rem);line-height:1;margin:.5em 0}}p{{color:#adbec4}}
a{{color:#67e8f9}}</style></head><body><main><small>Wideband · first website</small>
<h1>{title} is live.</h1><p>{agent} can shape this page with you. Tell your agent what this website should become.</p>
</main></body></html>
"""


def render_plist(port: int) -> bytes:
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": ["/opt/homebrew/bin/python3", str(SCRIPT), "--directory", str(PROJECT / "public"), "--port", str(port)],
        "RunAtLoad": True,
        "KeepAlive": True,
        "WorkingDirectory": str(PROJECT),
        "StandardOutPath": str(GOAL_DIR / "server.log"),
        "StandardErrorPath": str(GOAL_DIR / "server.log"),
    })


def site_ready(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
            if response.status != 200 or json.load(response).get("service") != "wideband-first-project":
                return False
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
            return (response.status == 200 and response.url == f"http://127.0.0.1:{port}/"
                    and response.headers.get_content_type() == "text/html" and bool(response.read(1)))
    except urllib.error.HTTPError as error:
        error.close()
        return False
    except Exception:
        return False


def start_server(port: int) -> None:
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    data = render_plist(port)
    if PLIST.exists() and PLIST.read_bytes() != data:
        existing = plistlib.loads(PLIST.read_bytes())
        if existing.get("Label") != LABEL:
            raise RuntimeError("an unrelated LaunchAgent occupies the first-project plist")
    fd, temp = tempfile.mkstemp(prefix=f".{PLIST.name}.", dir=PLIST.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, PLIST)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    if os.environ.get("WB_FIRST_GOAL_SKIP_LAUNCHD") == "1":
        return
    target = f"gui/{os.getuid()}/{LABEL}"
    if subprocess.run(["/bin/launchctl", "print", target], capture_output=True).returncode == 0:
        subprocess.run(["/bin/launchctl", "bootout", target], capture_output=True, check=False)
        for _ in range(20):
            if subprocess.run(["/bin/launchctl", "print", target], capture_output=True).returncode:
                break
            time.sleep(0.3)
        else:
            raise RuntimeError("previous first-project LaunchAgent did not stop")
    result = subprocess.run(["/bin/launchctl", "bootstrap", f"gui/{os.getuid()}", str(PLIST)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"first-project LaunchAgent failed to load: {result.stderr.strip()}")
    for _ in range(20):
        if site_ready(port):
            return
        time.sleep(0.25)
    raise RuntimeError("first-project service loaded but did not answer its health check")


def phone_url(port: int) -> str | None:
    candidates = [Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale"), Path("/opt/homebrew/bin/tailscale")]
    binary = next((path for path in candidates if path.is_file() and os.access(path, os.X_OK)), None)
    if binary is None:
        return None

    def existing() -> tuple[str | None, bool]:
        try:
            result = subprocess.run([str(binary), "serve", "status", "--json"], capture_output=True,
                                    text=True, timeout=8, env={**os.environ, "TAILSCALE_BE_CLI": "1"})
        except subprocess.TimeoutExpired:
            return None, False
        if result.returncode:
            return None, False
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None, False
        tcp = data.get("TCP") or {}
        funnel = data.get("AllowFunnel") or {}
        private_url = None
        for hostport, config in (data.get("Web") or {}).items():
            host, sep, tls_port = hostport.rpartition(":")
            if not sep or not (tcp.get(tls_port) or {}).get("HTTPS"):
                continue
            for path, handler in (config.get("Handlers") or {}).items():
                if (handler.get("Proxy") or "").rstrip("/") == f"http://127.0.0.1:{port}":
                    if funnel.get(hostport) is True:
                        # A public route to this site must never be described
                        # as a private phone link, even if another private
                        # Serve mapping also exists.
                        return None, True
                    suffix = "" if tls_port == "443" else f":{tls_port}"
                    private_url = f"https://{host}{suffix}{'' if path == '/' else path}"
        return private_url, False

    found, public = existing()
    if public:
        return None
    if not found:
        try:
            result = subprocess.run([str(binary), "serve", "--bg", f"--https={port}", f"http://127.0.0.1:{port}"],
                                    capture_output=True, text=True, timeout=15,
                                    env={**os.environ, "TAILSCALE_BE_CLI": "1"})
        except subprocess.TimeoutExpired:
            return None
        if result.returncode:
            return None
    # The Serve map proves configuration, not that TLS and the proxy answer.
    # Probe through the HTTPS entrypoint before handing a link to the phone.
    for _ in range(6):
        found, public = existing()
        if public:
            return None
        if found:
            try:
                with urllib.request.urlopen(found, timeout=3) as response:
                    expected = urllib.parse.urlsplit(found)
                    landed = urllib.parse.urlsplit(response.url)
                    page_ok = (response.status == 200
                               and landed.scheme == "https"
                               and landed.netloc == expected.netloc
                               and landed.path.rstrip("/") == expected.path.rstrip("/")
                               and response.headers.get_content_type() == "text/html"
                               and bool(response.read(1)))
                if page_ok:
                    health = found.rstrip("/") + "/health"
                    with urllib.request.urlopen(health, timeout=3) as response:
                        if (response.status == 200
                                and json.load(response).get("service")
                                == "wideband-first-project"):
                            return found
            except urllib.error.HTTPError as error:
                error.close()
            except (OSError, ValueError):
                pass
        time.sleep(1)
    return None


def register_fleetdeck(os_name: str, port: int, previous_name: str | None = None) -> None:
    registry = HOME / "srv" / "fleetdeck" / "services.json"
    if not registry.is_file():
        return
    data = json.loads(registry.read_text(encoding="utf-8"))
    services = data.get("services")
    if not isinstance(services, list):
        raise RuntimeError("Fleetdeck services.json has no services list")
    existing = next((item for item in services if isinstance(item, dict) and item.get("id") == SERVICE_ID), None)
    if existing:
        if existing.get("port") != port:
            raise RuntimeError("Fleetdeck first-project tile has a different port; review it before changing")
        if existing.get("source") != "wideband-first-goal" or existing.get("name") != previous_name:
            return
        existing["name"] = f"{os_name} · First project"
        existing["install"] = True
    else:
        services.append({"id": SERVICE_ID, "group": "apps", "port": port, "icon": "rocket", "name": f"{os_name} · First project", "blurb": "Your first Wideband website", "kind": "web", "install": True, "source": "wideband-first-goal"})
    tmp = registry.with_name(registry.name + f".wideband-{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.chmod(tmp, registry.stat().st_mode & 0o777)
        os.replace(tmp, registry)
    finally:
        tmp.unlink(missing_ok=True)


def retire_phone_route(port: int) -> str | None:
    candidates = [Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale"), Path("/opt/homebrew/bin/tailscale")]
    binary = next((path for path in candidates if path.is_file() and os.access(path, os.X_OK)), None)
    if binary is None:
        return None
    try:
        result = subprocess.run([str(binary), "serve", "status", "--json"],
                                capture_output=True, text=True, timeout=8,
                                env={**os.environ, "TAILSCALE_BE_CLI": "1"})
        if result.returncode:
            return "The old phone route could not be inspected. Review Tailscale Serve."
        data = json.loads(result.stdout)
        for hostport, config in (data.get("Web") or {}).items():
            _host, sep, tls_port = hostport.rpartition(":")
            if not sep or tls_port != str(port):
                continue
            handlers = config.get("Handlers") or {}
            if handlers != {"/": {"Proxy": f"http://127.0.0.1:{port}"}}:
                continue
            stopped = subprocess.run([str(binary), "serve", f"--https={port}", "off"],
                                     capture_output=True, text=True, timeout=10,
                                     env={**os.environ, "TAILSCALE_BE_CLI": "1"})
            if stopped.returncode:
                return "The old phone route is still configured. Review Tailscale Serve."
            return None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return "The old phone route could not be inspected. Review Tailscale Serve."
    return None


def retire_site(prior: dict) -> str | None:
    """Stop only the service created for the previous website choice."""
    if prior.get("goal") != "website":
        return None
    if PLIST.is_file():
        definition = plistlib.loads(PLIST.read_bytes())
        if definition.get("Label") != LABEL:
            raise RuntimeError("first-project LaunchAgent was changed; review it before retirement")
        if os.environ.get("WB_FIRST_GOAL_SKIP_LAUNCHD") != "1":
            target = f"gui/{os.getuid()}/{LABEL}"
            subprocess.run(["/bin/launchctl", "bootout", target], capture_output=True, check=False)
            for _ in range(20):
                if subprocess.run(["/bin/launchctl", "print", target], capture_output=True).returncode:
                    break
                time.sleep(0.3)
            else:
                raise RuntimeError("previous first-project LaunchAgent did not stop")
        PLIST.unlink()
    warning = retire_phone_route(prior["port"]) if isinstance(prior.get("port"), int) else None
    registry = HOME / "srv" / "fleetdeck" / "services.json"
    if registry.is_file() and isinstance(prior.get("port"), int):
        data = json.loads(registry.read_text(encoding="utf-8"))
        services = data.get("services")
        if isinstance(services, list):
            retained = [item for item in services if not (
                isinstance(item, dict) and item.get("id") == SERVICE_ID
                and item.get("source") == "wideband-first-goal"
                and item.get("port") == prior["port"]
            )]
            if len(retained) != len(services):
                data["services"] = retained
                temp = registry.with_name(registry.name + f".wideband-{os.getpid()}.tmp")
                try:
                    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                    os.chmod(temp, registry.stat().st_mode & 0o777)
                    os.replace(temp, registry)
                finally:
                    temp.unlink(missing_ok=True)
    return warning


def apply() -> dict:
    os_name, agent_name, goal = identity()
    prior = read_status()
    GOAL_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(GOAL_DIR, 0o700)
    PROJECT.mkdir(parents=True, exist_ok=True)
    status: dict = {"goal": goal, "os_name": os_name, "agent_name": agent_name,
                    "service_id": SERVICE_ID if goal == "website" else None,
                    "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    port = selected_port(prior) if goal == "website" else None
    private_json(STATUS, status | {"status": "preparing"})
    if goal == "website":
        assert port is not None
        previous_hash = prior.get("generated_page_hash")
        if not previous_hash and prior.get("goal") == "website" and prior.get("os_name") and prior.get("agent_name"):
            previous_hash = hashlib.sha256(site_content(prior["os_name"], prior["agent_name"]).encode("utf-8")).hexdigest()
        status["generated_page_hash"] = write_generated(
            PROJECT / "public" / "index.html", site_content(os_name, agent_name), previous_hash)
        icon = PROJECT / "public" / "icons" / "apple-touch-icon.png"
        icon.parent.mkdir(parents=True, exist_ok=True)
        if not icon.exists():
            if not BRAND_ICON.is_file():
                raise RuntimeError("Wideband brand icon is missing from the setup package")
            shutil.copyfile(BRAND_ICON, icon)
        manifest = json.dumps({
            "name": f"{os_name} · First project", "short_name": os_name,
            "start_url": "/", "scope": "/", "display": "standalone",
            "background_color": "#111923", "theme_color": "#111923",
            "icons": [{"src": "/icons/apple-touch-icon.png", "sizes": "1508x1508", "type": "image/png"}],
        }, ensure_ascii=False, indent=2) + "\n"
        status["generated_manifest_hash"] = write_generated(
            PROJECT / "public" / "manifest.webmanifest", manifest, prior.get("generated_manifest_hash"))
        start_server(port)
        if os.environ.get("WB_FIRST_GOAL_SKIP_LAUNCHD") != "1" and not site_ready(port):
            raise RuntimeError("first-project preview did not answer its health check")
        register_fleetdeck(os_name, port, f"{prior.get('os_name')} · First project" if prior.get("goal") == "website" else None)
        ready = site_ready(port)
        status.update({"status": "ready" if ready else "prepared", "port": port,
                       "local_url": f"http://127.0.0.1:{port}/"})
        if ready and os.environ.get("WB_FIRST_GOAL_SKIP_LAUNCHD") != "1":
            reachable = phone_url(port)
            if reachable:
                status["phone_url"] = reachable
    else:
        warning = retire_site(prior)
        if warning:
            status["retirement_warning"] = warning
        text = (f"# {goal.title()} with {agent_name}\n\n"
                f"{os_name} is ready for its first {goal} request. Text {agent_name} the topic and desired outcome.\n")
        previous_hash = prior.get("generated_brief_hash")
        if not previous_hash and prior.get("goal") in {"research", "proposal"} and prior.get("os_name") and prior.get("agent_name"):
            old = (f"# {prior['goal'].title()} with {prior['agent_name']}\n\n"
                   f"{prior['os_name']} is ready for its first {prior['goal']} request. Text {prior['agent_name']} the topic and desired outcome.\n")
            previous_hash = hashlib.sha256(old.encode("utf-8")).hexdigest()
        status["generated_brief_hash"] = write_generated(PROJECT / "FIRST-GOAL.md", text, previous_hash)
        status["status"] = "prepared"
    private_json(STATUS, status)
    return status


def check() -> dict:
    os_name, agent_name, goal = identity()
    status = read_status()
    if status.get("goal") != goal or status.get("os_name") != os_name or status.get("agent_name") != agent_name:
        raise RuntimeError("the first-goal installation does not match current onboarding choices")
    if goal == "website" and (status.get("status") != "ready" or not isinstance(status.get("port"), int) or not site_ready(status["port"])):
        raise RuntimeError("first-project preview is not serving its health route")
    if goal != "website" and (status.get("status") != "prepared" or not (PROJECT / "FIRST-GOAL.md").is_file()):
        raise RuntimeError("first-goal brief is missing")
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "apply", "check"))
    args = parser.parse_args()
    try:
        if args.action == "plan":
            os_name, agent_name, goal = identity()
            result = {"os_name": os_name, "agent_name": agent_name, "goal": goal,
                      "project": str(PROJECT), "needs_preview_server": goal == "website"}
        else:
            result = apply() if args.action == "apply" else check()
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"first goal: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
