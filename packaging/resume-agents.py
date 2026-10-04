#!/usr/bin/env python3
"""Restore previously activated local agents once at GUI login."""

import os
from pathlib import Path
import sys

import customer_agent_provision

if (Path.home() / ".wideband/setup/deactivated").exists():
    raise SystemExit(0)
try:
    for agent in customer_agent_provision.resume_agents():
        print(f"{agent['name']}: {agent['state']}")
except (OSError, ValueError) as error:
    print(f"Agent resume needs attention: {error}", file=sys.stderr)
    raise SystemExit(1)
