#!/usr/bin/env python3
"""Read-only, redacted local tmux fleet snapshot for Fleetdeck."""

from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from tm_fleet_common import resolve_sessions_conf

VERSION = "1.0.0"
SCHEMA = "agent-fleet.snapshot.v1"
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")
HOST_ALIAS = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,39}$")
TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,49}$")
VERSION_COMMAND = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
DEFAULT_AGENTS = {"node", "claude", "codex", "dsh"}
DEFAULT_SHELLS = {"zsh", "bash", "sh", "fish"}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def epoch(value: str) -> str | None:
    try:
        return dt.datetime.fromtimestamp(int(value), dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except (ValueError, OverflowError, OSError):
        return None


def mtime(path: Path) -> str | None:
    try:
        return epoch(str(int(path.stat().st_mtime)))
    except OSError:
        return None


def safe_name(value: object) -> str | None:
    if not isinstance(value, str) or not NAME.fullmatch(value):
        return None
    try:
        ipaddress.ip_address(value)
        return None
    except ValueError:
        return value


def source_status(path: Path, label: str) -> dict:
    """Private diagnostics; caller never places path in JSON."""
    try:
        path.stat()
        status = "available" if path.is_file() or path.is_dir() else "unavailable"
    except OSError:
        status = "unavailable"
    return {"source": label, "path": str(path), "status": status}


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def read_json(path: Path) -> dict | None:
    text = read_text(path)
    if text is None:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def frontmatter(text: str) -> dict:
    """Parse only simple scalar/list fields from tm-memory cards."""
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return {}
    end = next((i for i, line in enumerate(lines[1:], 1) if line == "---"), None)
    if end is None:
        return {}
    result: dict[str, object] = {}
    current: str | None = None
    for line in lines[1:end]:
        if line.startswith("  - ") and current is not None:
            result.setdefault(current, []).append(line[4:].strip())
        elif not line.startswith(" ") and ":" in line:
            key, value = line.split(":", 1)
            if re.fullmatch(r"[a-z_]+", key):
                result[key] = value.strip() if value.strip() else []
                current = key if not value.strip() else None
    return result


def standard_sessions(path: Path) -> dict[str, str] | None:
    text = read_text(path)
    if text is None:
        return None
    result = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or "=" not in line:
            continue
        name, root = (part.strip() for part in line.split("=", 1))
        if safe_name(name) and root:
            result[name] = os.path.abspath(os.path.expanduser(os.path.expandvars(root)))
    return result


def devices(path: Path) -> tuple[list[str], int] | None:
    text = read_text(path)
    if text is None:
        return None
    aliases = []
    excluded = 0
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" in line:
            alias = line.split("=", 1)[0].strip()
            if HOST_ALIAS.fullmatch(alias):
                aliases.append(alias)
            else:
                excluded += 1
    return sorted(set(aliases)), excluded


def tmux_query(socket: str | None, *args: str) -> list[str] | None:
    cmd = ["tmux"]
    if socket:
        cmd += ["-L", socket]
    cmd.extend(args)
    try:
        result = subprocess.run(cmd, text=True, capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.splitlines() if result.returncode == 0 else None


def tab_fields(lines: list[str] | None, count: int) -> list[list[str]]:
    if lines is None:
        return []
    return [parts for line in lines if len(parts := line.split("\t")) == count]


def process(command: str, agents: set[str], shells: set[str]) -> dict:
    if command in shells:
        return {"classification": "shell", "engine": None, "display": "Shell", "basis": "shell_command"}
    if VERSION_COMMAND.fullmatch(command):
        return {"classification": "recognized_engine", "engine": "claude_code", "display": "Claude Code", "basis": "version_command_heuristic"}
    if command in agents:
        engine = {"claude": "claude_code", "codex": "codex", "dsh": "dsh"}.get(command)
        return {"classification": "recognized_engine" if engine else "agent_like_process", "engine": engine, "display": {"claude_code": "Claude Code", "codex": "Codex", "dsh": "DSH"}.get(engine, "Configured agent process"), "basis": "configured_command"}
    return {"classification": "unknown", "engine": None, "display": "Unknown process", "basis": "unrecognized"}


def slug(value: str) -> str:
    return value.lower().replace("_", "-").replace(".", "-")


def within(path: str | None, root: str | None) -> bool | None:
    if not path or not root or not os.path.isabs(path):
        return None
    try:
        canonical_path = os.path.realpath(os.path.expanduser(path))
        canonical_root = os.path.realpath(os.path.expanduser(root))
        return os.path.commonpath((canonical_path, canonical_root)) == canonical_root
    except (OSError, ValueError):
        return None


def expand_root(value: object) -> str | None:
    if not isinstance(value, str) or not value or value.upper() == "UNVERIFIED":
        return None
    expanded = os.path.expanduser(os.path.expandvars(value))
    return os.path.realpath(expanded) if os.path.isabs(expanded) else None


def router_pane_ready(command: str, agents: set[str], shells: set[str]) -> bool:
    """Mirror imsg-router pane_has_agent, without asserting delivery occurred."""
    if not command:
        return False
    lowered = command.lower()
    if lowered in {item.lower() for item in shells}:
        return False
    if lowered in {item.lower() for item in agents}:
        return True
    return command[0].isdigit() or lowered.startswith("node")


def collect(args: argparse.Namespace) -> tuple[dict, list[dict]]:
    stamp = now()
    home = Path.home()
    standard_path = Path(args.sessions_conf).expanduser() if args.sessions_conf else resolve_sessions_conf()
    devices_path = Path(args.devices_conf).expanduser() if args.devices_conf else standard_path.parent / "devices.conf"
    memory_path = Path(os.environ.get("TM_MEMORY_DIR") or home / ".config/agent-session-memory")
    routing_path = Path(os.environ.get("TM_ROUTING") or home / ".imsg-routing.json")
    chatbind_path = Path(os.environ.get("TM_CHATBIND") or home / ".imsg-chatbind.json")
    diagnostics = [source_status(path, ref) for ref, path in (("sessions_conf", standard_path), ("devices_conf", devices_path), ("identity_cards", memory_path / "identity"), ("state_cards", memory_path / "state"), ("routing_descriptions", routing_path), ("chatbind", chatbind_path))]
    unknowns: list[dict] = []

    def unknown(kind: str, source: str, detail: str, ident: str | None = None):
        unknowns.append({"id": ident or f"unknown:{source}:{len(unknowns)+1}", "kind": kind, "source": source, "as_of": stamp, "detail": detail})

    declared = standard_sessions(standard_path)
    if declared is None:
        unknown("source_unavailable", "sessions_conf", "Session standard could not be read; declared status is unknown.")
    device_result = devices(devices_path)
    device_aliases = device_result[0] if device_result is not None else None
    if device_result is None:
        unknown("source_unavailable", "devices_conf", "Device aliases could not be read; reachability was not checked.")
    elif device_result[1]:
        unknown("invalid_metadata", "devices_conf", f"{device_result[1]} device entries were excluded because their alias was unsafe.")
    routing = read_json(routing_path)
    if routing is None:
        unknown("source_unavailable", "routing_descriptions", "Router config could not be read; description links are unknown.")
    chatbind = read_json(chatbind_path)
    if chatbind is None:
        unknown("source_unavailable", "chatbind", "Bound-chat config could not be read; bindings are unknown.")

    identity_dir = memory_path / "identity"
    state_dir = memory_path / "state"
    identities: dict[str, tuple[dict, Path]] | None = {}
    states: dict[str, tuple[dict, Path]] | None = {}
    for directory, target, ref in ((identity_dir, identities, "identity_cards"), (state_dir, states, "state_cards")):
        if not directory.is_dir():
            if ref == "identity_cards":
                identities = None
            else:
                states = None
            unknown("source_unavailable", ref, "Card directory could not be read; card presence is unknown.")
            continue
        try:
            paths = list(directory.glob("*.md"))
        except OSError:
            paths = []
            if ref == "identity_cards":
                identities = None
            else:
                states = None
            unknown("source_unavailable", ref, "Card directory could not be enumerated.")
        for path in paths:
            if not safe_name(path.stem):
                continue
            text = read_text(path)
            if text is None:
                target[path.stem] = ({}, path)
                unknown("source_unavailable", ref, "A card could not be read.")
                continue
            card = frontmatter(text)
            if card:
                target[path.stem] = (card, path)

    socket = os.environ.get("TM_TMUX_SOCKET")
    sessions_raw = tmux_query(socket, "list-sessions", "-F", "#{session_name}\t#{session_created}\t#{session_activity}")
    windows_raw = tmux_query(socket, "list-windows", "-a", "-F", "#{session_name}\t#{window_index}\t#{window_active}") if sessions_raw is not None else None
    panes_raw = tmux_query(socket, "list-panes", "-a", "-F", "#{session_name}\t#{window_index}\t#{pane_id}\t#{pane_index}\t#{pane_active}\t#{pane_dead}\t#{pane_current_command}\t#{pane_current_path}") if windows_raw is not None else None
    if sessions_raw is None:
        unknown("source_unavailable", "tmux", "Local tmux sessions could not be listed; live status is unknown.")
    elif windows_raw is None or panes_raw is None:
        unknown("source_unavailable", "tmux", "Local tmux hierarchy could not be fully listed.")
    observed_sessions = {fields[0]: fields for fields in tab_fields(sessions_raw, 3) if safe_name(fields[0])}
    windows = [fields for fields in tab_fields(windows_raw, 3) if safe_name(fields[0]) and fields[1].isdigit()]
    panes = [fields for fields in tab_fields(panes_raw, 8) if safe_name(fields[0]) and fields[1].isdigit() and re.fullmatch(r"%[0-9]+", fields[2])]
    if sessions_raw is not None and len(observed_sessions) != len(sessions_raw):
        unknown("invalid_metadata", "tmux", "Some session names or records were excluded because they are not safe identifiers.")

    route_sessions = routing.get("sessions", {}) if routing else {}
    if not isinstance(route_sessions, dict):
        route_sessions = {}
        unknown("invalid_metadata", "routing_descriptions", "Router session descriptions were not a mapping.")
    bound = chatbind.get("bound", []) if chatbind else []
    if not isinstance(bound, list):
        bound = []
        unknown("invalid_metadata", "chatbind", "Bound chat entries were not a list.")
    names = set(observed_sessions) | set(declared or {}) | set(identities or {}) | set(states or {})
    for entry in bound:
        if isinstance(entry, dict) and safe_name(entry.get("session")):
            names.add(entry["session"])
    agents = set(routing.get("agent_pane_commands", DEFAULT_AGENTS)) if routing and isinstance(routing.get("agent_pane_commands"), list) else DEFAULT_AGENTS
    shells = set(routing.get("shell_pane_commands", DEFAULT_SHELLS)) if routing and isinstance(routing.get("shell_pane_commands"), list) else DEFAULT_SHELLS
    agents = {x for x in agents if isinstance(x, str) and TOKEN.fullmatch(x)}
    shells = {x for x in shells if isinstance(x, str) and TOKEN.fullmatch(x)}
    active_windows = {(name, index) for name, index, active in windows if active == "1"}
    active_cwds: dict[str, str] = {}
    for name, index, _pane_id, _pane_index, active, _dead, _command, cwd in panes:
        if active == "1" and (name, index) in active_windows:
            active_cwds[name] = cwd
    nodes: dict[str, dict] = {}
    edges: dict[str, dict] = {}

    def node(data: dict):
        nodes[data["id"]] = data

    def edge(source: str, dest: str, kind: str, evidence: str, ref: str, display: str, status: str = "configured-only", source_time: str | None = None):
        if source not in nodes or dest not in nodes:
            return
        ident = f"{kind}:{source}:{dest}"
        edges[ident] = {"id": ident, "from": source, "to": dest, "type": kind, "evidence": evidence, "source": ref, "freshness": {"as_of": stamp, "source_mtime": source_time, "status": status}, "display": display}

    node({"id": f"host:{args.host_id}", "type": "host", "label": args.host_id, "parent_id": None, "declared": True, "observed": True if sessions_raw is not None else None, "reachability": "local" if sessions_raw is not None else "unknown_not_checked", "source_refs": ["tmux"], "observed_at": stamp if sessions_raw is not None else None})
    for alias in device_aliases or []:
        if alias != args.host_id:
            node({"id": f"host:{alias}", "type": "host", "label": alias, "parent_id": None, "declared": True, "observed": None, "reachability": "unknown_not_checked", "source_refs": ["devices_conf"], "observed_at": None})

    by_session_windows: dict[str, int] = {}
    for fields in windows:
        by_session_windows[fields[0]] = by_session_windows.get(fields[0], 0) + 1
    for name in sorted(names):
        identity = (identities or {}).get(name)
        state = (states or {}).get(name)
        card = identity[0] if identity else {}
        state_card = state[0] if state else {}
        role = card.get("role") if card.get("role") in ("assigned", "unassigned") else None
        status = state_card.get("status") if state_card.get("status") in ("idle", "working", "blocked", "awaiting-approval", "handoff", "retired") else None
        live = observed_sessions.get(name)
        standard_root = (declared or {}).get(name)
        card_root = expand_root(card.get("root"))
        root_match = os.path.realpath(card_root) == os.path.realpath(standard_root) if card_root and standard_root else None
        cwd_in_card = within(active_cwds.get(name), card_root) if panes_raw is not None else None
        cwd_in_standard = within(active_cwds.get(name), standard_root) if panes_raw is not None else None
        refs = ["tmux"] if live else []
        if standard_root:
            refs.append("sessions_conf")
        if identity:
            refs.append("identity_cards")
        if state:
            refs.append("state_cards")
        node({"id": f"session:{name}", "type": "session", "label": name, "parent_id": f"host:{args.host_id}", "declared": name in declared if declared is not None else None, "observed": name in observed_sessions if sessions_raw is not None else None, "standard": {"present": name in declared if declared is not None else None, "source_mtime": mtime(standard_path)}, "runtime": {"window_count": by_session_windows.get(name, 0) if windows_raw is not None and live else None, "created_at": epoch(live[1]) if live else None, "last_activity_at": epoch(live[2]) if live else None}, "identity": {"card_present": identity is not None if identities is not None else None, "stable_session_id": f"session:{name}", "role": role, "card_updated_date": card.get("updated") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(card.get("updated", ""))) else None, "card_file_mtime": mtime(identity[1]) if identity else None, "verified_agent_id": None}, "state": {"card_present": state is not None if states is not None else None, "status": status, "updated_date": state_card.get("updated") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(state_card.get("updated", ""))) else None}, "root_evidence": {"card_vs_standard_match": root_match, "observed_cwd_within_card": cwd_in_card, "observed_cwd_within_standard": cwd_in_standard, "source_refs": [r for r in ("identity_cards" if card_root else None, "sessions_conf" if standard_root else None, "tmux" if active_cwds.get(name) else None) if r], "as_of": stamp}, "source_refs": refs, "observed_at": stamp if live else None})

    for name, index, active in windows:
        if f"session:{name}" not in nodes:
            continue
        node({"id": f"window:{name}:{index}", "type": "window", "label": f"Window {index}", "parent_id": f"session:{name}", "declared": False, "observed": True, "index": int(index), "runtime": {"active": active == "1", "pane_count": 0 if panes_raw is not None else None}, "source_refs": ["tmux"], "observed_at": stamp})
    for name, index, pane_id, pane_index, active, dead, command, cwd in panes:
        window_id = f"window:{name}:{index}"
        if window_id not in nodes:
            continue
        root = (declared or {}).get(name)
        in_standard = within(cwd, root)
        card = (identities or {}).get(name)
        card_root = expand_root(card[0].get("root")) if card else None
        in_card = within(cwd, card_root)
        root_scope = "within_standard" if in_standard is True else "outside_standard" if in_standard is False else "unknown"
        node({"id": f"pane:{name}:{pane_id}", "type": "pane", "label": f"Pane {pane_index}", "parent_id": window_id, "declared": False, "observed": True, "pane_id": pane_id, "pane_index": int(pane_index) if pane_index.isdigit() else None, "active": active == "1", "dead": dead == "1", "process": process(command, agents, shells), "observed_cwd_scope": root_scope, "observed_cwd_within_card": in_card, "observed_cwd_within_standard": in_standard, "verified_agent_id": None, "source_refs": ["tmux", "tm_memory_classification_rule"], "observed_at": stamp})
        if nodes[window_id]["runtime"]["pane_count"] is not None:
            nodes[window_id]["runtime"]["pane_count"] += 1

    excluded = {x.lower() for x in routing.get("exclude", []) if isinstance(x, str)} if routing and isinstance(routing.get("exclude"), list) else set()
    if routing is not None and sessions_raw is not None:
        node({"id": "chat:router-command", "type": "chat", "label": "Router command channel", "parent_id": None, "declared": True, "observed": None, "source_refs": ["routing_descriptions", "imsg-router#live_sessions"], "observed_at": None})
        for name in sorted(observed_sessions):
            if name.lower() in excluded:
                nodes[f"session:{name}"]["router"] = {"addressable": False, "agent_pane_ready": None, "policy_basis": "on_disk_config", "active_process_policy_verified": False, "as_of": stamp, "source_refs": ["imsg-router#live_sessions", "routing_descriptions"]}
                continue
            edge("chat:router-command", f"session:{name}", "router_addressable", "computed", "imsg-router#live_sessions", "Eligible by on-disk router policy at snapshot time; running router policy unverified", "snapshot-computed")
            check = tmux_query(socket, "display-message", "-p", "-t", name, "#{pane_current_command}")
            ready = router_pane_ready(check[0].strip() if check else "", agents, shells) if check is not None else None
            nodes[f"session:{name}"]["router"] = {"addressable": True, "agent_pane_ready": ready, "policy_basis": "on_disk_config", "active_process_policy_verified": False, "as_of": stamp, "source_refs": ["imsg-router#live_sessions", "imsg-router#pane_has_agent", "tmux"]}
            if ready is None:
                unknown("source_unavailable", "tmux", "An active-pane router check could not be completed.")
            elif ready:
                edge("chat:router-command", f"session:{name}", "router_agent_pane_ready", "computed", "imsg-router#pane_has_agent", "Active pane passes on-disk router check at snapshot time; running router policy and delivery unverified", "snapshot-computed")
    else:
        for name in observed_sessions:
            nodes[f"session:{name}"]["router"] = {"addressable": None, "agent_pane_ready": None, "as_of": stamp, "source_refs": ["routing_descriptions", "tmux"]}

    if routing is not None:
        live_described = [name for name in route_sessions if safe_name(name) and name in observed_sessions]
        for name in live_described:
            edge("chat:router-command", f"session:{name}", "describes_session", "declared", "routing_descriptions", "Described live target in routing config", source_time=mtime(routing_path))
        missing = sum(1 for name in route_sessions if safe_name(name) and name not in observed_sessions) if sessions_raw is not None else 0
        if missing and sessions_raw is not None:
            unknown("unmatched_description", "routing_descriptions", f"{missing} router descriptions have no matching live session; this mapping is not a route allowlist.")

    seen_chat_ids: set[str] = set()
    if chatbind is not None:
        for entry in bound:
            if not isinstance(entry, dict):
                continue
            name = safe_name(entry.get("session"))
            raw_id = entry.get("chat_id")
            if not name or raw_id is None or str(raw_id) in seen_chat_ids:
                unknown("invalid_metadata", "chatbind", "A bound-chat entry was incomplete or duplicated.")
                continue
            seen_chat_ids.add(str(raw_id))
            cid = f"chat:bound-{name}"
            if cid in nodes:
                unknown("invalid_metadata", "chatbind", "More than one bound chat names the same session.")
                continue
            node({"id": cid, "type": "chat", "label": f"Bound chat → {name}", "parent_id": None, "declared": True, "observed": None, "source_refs": ["chatbind"], "observed_at": None})
            edge(cid, f"session:{name}", "chat_routes_to", "declared", "chatbind", "Bound chat ownership; delivery not observed", source_time=mtime(chatbind_path))
            if name not in observed_sessions and sessions_raw is not None:
                unknown("target_not_live", "chatbind", "A bound chat targets a session that is not currently live.")

    omitted_resource_fragments = 0
    if identities is not None:
        for name, (card, path) in identities.items():
            source_id = f"session:{name}"
            if source_id not in nodes:
                continue
            for item in card.get("routing_out", []) if isinstance(card.get("routing_out"), list) else []:
                match = re.match(r"^session:([A-Za-z0-9][A-Za-z0-9._-]{0,39})(?:\b|\s|$)", item)
                if match:
                    target = match.group(1)
                    target_id = f"session:{target}"
                    if target_id not in nodes:
                        node({"id": target_id, "type": "session", "label": target, "parent_id": f"host:{args.host_id}", "declared": target in declared if declared is not None else None, "observed": target in observed_sessions if sessions_raw is not None else None, "standard": {"present": target in declared if declared is not None else None}, "runtime": {}, "identity": {"card_present": False, "verified_agent_id": None}, "state": {"card_present": None}, "root_evidence": {}, "source_refs": ["identity_cards"], "observed_at": None})
                        unknown("unresolved_reference", "identity_cards", "A handoff names a session missing from the inventory.")
                    edge(source_id, target_id, "hands_off_to", "declared", f"identity:{name}#routing_out", "Declared handoff", source_time=mtime(path))
            for item in card.get("tools", []) if isinstance(card.get("tools"), list) else []:
                for token in item.split(","):
                    token = token.strip()
                    script = re.fullmatch(r"(?:[A-Za-z0-9_.-]+/)*([A-Za-z][A-Za-z0-9_.-]*\.(?:sh|mjs|py|ts))", token)
                    if script:
                        file_name = script.group(1)
                        file_id = f"file:{slug(token.replace('/', '-'))}"
                        node({"id": file_id, "type": "file", "label": file_name, "parent_id": None, "declared": True, "observed": None, "source_refs": [f"identity:{name}#tools"], "observed_at": None})
                        edge(source_id, file_id, "executes_file", "declared", f"identity:{name}#tools", "Listed script", source_time=mtime(path))
                        continue
                    if not TOKEN.fullmatch(token):
                        if token:
                            omitted_resource_fragments += 1
                        continue
                    tool_id = f"tool:{slug(token)}"
                    node({"id": tool_id, "type": "tool", "label": token, "parent_id": None, "declared": True, "observed": None, "source_refs": [f"identity:{name}#tools"], "observed_at": None})
                    edge(source_id, tool_id, "uses_tool", "declared", f"identity:{name}#tools", "Listed tool", source_time=mtime(path))

    if omitted_resource_fragments:
        unknown("omitted_resource_reference", "identity_cards", f"{omitted_resource_fragments} card tool-list fragments were prose or ambiguous; no resource link was inferred.")

    def safe_source_status(entry: dict) -> str:
        if entry["status"] == "available" and any(item["kind"] == "source_unavailable" and item["source"] == entry["source"] for item in unknowns):
            return "partial"
        return entry["status"]

    sources = [{"id": entry["source"], "status": safe_source_status(entry), "as_of": stamp, "source_mtime": mtime(Path(entry["path"]))} for entry in diagnostics]
    sources.append({"id": "tmux", "status": "unavailable" if sessions_raw is None else "partial" if windows_raw is None or panes_raw is None else "available", "as_of": stamp, "source_mtime": None})
    degraded = any(item["kind"] == "source_unavailable" for item in unknowns)
    result = {"schema_version": SCHEMA, "collected_at": stamp, "nodes": sorted(nodes.values(), key=lambda n: n["id"]), "edges": sorted(edges.values(), key=lambda e: e["id"]), "sources": sources, "summary": {"source_health": "degraded" if degraded else "complete", "hosts": len([n for n in nodes.values() if n["type"] == "host"]), "remote_hosts_unchecked": sum(alias != args.host_id for alias in device_aliases) if device_aliases is not None else None, "declared_sessions": len(declared) if declared is not None else None, "live_sessions": len(observed_sessions) if sessions_raw is not None else None, "identity_cards": len(identities) if identities is not None else None, "windows": len(windows) if windows_raw is not None else None, "panes": len(panes) if panes_raw is not None else None, "verified_agent_nodes": 0, "bound_chat_declarations": len([e for e in edges.values() if e["type"] == "chat_routes_to"]) if chatbind is not None else None, "routing_descriptions": len([e for e in edges.values() if e["type"] == "describes_session"]) if routing is not None else None, "semantic_edges": len(edges)}, "unknowns": unknowns}
    return result, diagnostics


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only, metadata-only local fleet graph snapshot")
    parser.add_argument("--json", action="store_true", help="emit redacted agent-fleet.snapshot.v1 JSON (default)")
    parser.add_argument("--version", action="version", version=f"tm-fleet-snapshot {VERSION} ({SCHEMA})")
    parser.add_argument("--host-id", default="local", help="safe local host alias; default local")
    parser.add_argument("--sessions-conf", help="explicit sessions.conf path for this invocation")
    parser.add_argument("--devices-conf", help="explicit devices.conf path for this invocation")
    parser.add_argument("--source-status", action="store_true", help="print private source paths and status to stderr; never included in JSON")
    args = parser.parse_args()
    if not HOST_ALIAS.fullmatch(args.host_id):
        parser.error("--host-id must be a safe alias")
    result, diagnostics = collect(args)
    if args.source_status:
        for item in diagnostics:
            print(f"{item['source']}: {item['status']} {item['path']}", file=sys.stderr)
    json.dump(result, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
