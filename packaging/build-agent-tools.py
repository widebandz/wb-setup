#!/usr/bin/env python3
"""Build the pinned Playwright/Chromium bundle, without running browsers."""
from pathlib import Path
import shutil
import sys
from agent_tools import build, verify

if len(sys.argv) != 3:
    raise SystemExit("usage: build-agent-tools.py TARGET VERIFIED_NODE")
target = Path(sys.argv[1]).resolve()
cached = Path(__file__).resolve().parents[1] / "vendor/agent-tools"
if target != cached and cached.is_dir():
    verify(cached)
    if target.exists():
        verify(target)
    else:
        shutil.copytree(cached, target, symlinks=True)
else:
    build(target, Path(sys.argv[2]).resolve())
