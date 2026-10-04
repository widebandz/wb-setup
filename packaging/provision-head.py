#!/usr/bin/env python3
"""Create the local head through the same provisioner as Fleetdeck."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import agent_tools
import customer_agent_provision

ROOT = Path(__file__).resolve().parents[1]


def run() -> None:
    path = Path.home() / ".wideband/setup/state.json"
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, encoding="utf-8") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size > 1024 * 1024):
            raise ValueError("private onboarding state is unavailable")
        data = json.load(stream)
    if data.get("metadata", {}).get("agent_provider") != "claude":
        raise ValueError("choose Claude Code to activate the supported head-agent path")
    tools = {}
    for name in ("python3", "node", "tmux"):
        result = subprocess.run([str(ROOT / "lib/toolchain-path"), name],
                                capture_output=True, text=True, timeout=20, check=False)
        path = Path(result.stdout.strip())
        if result.returncode or not path.is_absolute() or not path.is_file():
            raise ValueError("verified agent tools are unavailable")
        tools[name] = path
    os.environ.update(agent_tools.environment(ROOT / "vendor/agent-tools", tools["node"]))
    os.environ["FLEETDECK_VERIFIED_TMUX"] = str(tools["tmux"])
    os.environ["FLEETDECK_VERIFIED_PYTHON"] = str(tools["python3"])
    os.environ["WB_AGENT_COMMAND"] = str(ROOT / "packaging/agent-command.py")
    customer_agent_provision.seed_default_roster()
    status = customer_agent_provision.activate_agent("wb-head")
    if status["state"] != "process_observed":
        raise ValueError("head-agent launch still needs attention")
    print("Local head agent is running and linked to the Agent fleet and Live Terminal Network.")
    print("Python, Node and Playwright browser tools are available. Connect Messages in the guide when ready.")


if __name__ == "__main__":
    try:
        run()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Head-agent provisioning needs attention: {error}", file=sys.stderr)
        raise SystemExit(1)
