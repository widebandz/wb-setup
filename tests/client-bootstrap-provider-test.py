#!/usr/bin/env python3
"""The packaged client must defer provider and operator-file changes."""

import os
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "bootstrap.sh").read_text(encoding="utf-8")


def section(start: str, end: str) -> str:
    assert start in SOURCE and end in SOURCE
    return SOURCE.split(start, 1)[1].split(end, 1)[0]


provider = section("# ── 1. the agent, first", "# ── 2. the repo")
context = section("# ── 5. the artifacts that need no Homebrew", "# ── 6. the human queue")
identity_shell = section("if [ \"$CLIENT_MODE\" != \"1\" ] && ! grep -qs 'sop-vars'", "# ── 5. the artifacts that need no Homebrew")
identity_shell = "if [ \"$CLIENT_MODE\" != \"1\" ] && ! grep -qs 'sop-vars'" + identity_shell

with tempfile.TemporaryDirectory(prefix="wb-client-bootstrap-provider-") as temporary:
    home = Path(temporary)
    env = {**os.environ, "HOME": str(home), "ROOT": str(ROOT),
           "CLIENT_MODE": "1", "DO_CLAUDE": "1", "ORG": "wideband"}
    prefix = 'step() { :; }; say() { :; }; bootstrap_status() { :; }; set -uo pipefail; '
    for snippet in (provider, identity_shell, context):
        result = subprocess.run(["/bin/bash", "-c", prefix + snippet],
                                env=env, capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
    assert not (home / ".zshrc").exists(), "client bootstrap edited the shell profile"
    assert not (home / ".claude").exists(), "client bootstrap created operator Claude files"

    # The standalone operator path keeps its previous behavior.
    env.update(CLIENT_MODE="0", DO_CLAUDE="0")
    for snippet in (provider, identity_shell, context):
        result = subprocess.run(["/bin/bash", "-c", prefix + snippet],
                                env=env, capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
    assert (home / ".zshrc").is_file(), "source bootstrap lost its shell setup"
    assert (home / ".claude" / "SOP.md").is_file(), "source bootstrap lost its operator guide"
    assert (home / ".claude" / "CLAUDE.md").is_file(), "source bootstrap lost its operator context"

print("client bootstrap defers provider and operator files; source bootstrap preserved")
