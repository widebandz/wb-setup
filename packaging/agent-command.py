#!/usr/bin/env python3
"""Fixed fleet operations for local agents; task text is read from stdin."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

import agent_tools
import customer_agent_provision

ROOT = Path(__file__).resolve().parents[1]


def configure() -> None:
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
    os.environ["WB_AGENT_COMMAND"] = str(Path(__file__).resolve())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("list", "activate", "delegate"))
    parser.add_argument("name", nargs="?")
    args = parser.parse_args()
    if args.action != "list" and not args.name:
        parser.error("an agent name is required")
    configure()
    if args.action == "list":
        result = customer_agent_provision.list_agents()
    elif args.action == "activate":
        result = customer_agent_provision.activate_agent(args.name)
    else:
        task = sys.stdin.read(12001)
        result = customer_agent_provision.delegate_task(args.name, task)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Agent operation needs attention: {error}", file=sys.stderr)
        raise SystemExit(1)
