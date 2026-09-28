#!/usr/bin/env python3
"""Run bootstrap's real guided handoff under a pseudo-terminal."""

import os
import pathlib
import pty
import subprocess
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
source = (ROOT / "bootstrap.sh").read_text(encoding="utf-8")
marker = "# The guided installer is the normal handoff"
assert marker in source

with tempfile.TemporaryDirectory() as directory:
    work = pathlib.Path(directory)
    snippet = work / "handoff.sh"
    snippet.write_text(source[source.index(marker):], encoding="utf-8")
    (work / "setup.sh").write_text(
        '#!/bin/bash\n: > "$WB_TEST_ARGS"\nfor arg in "$@"; do printf "%s\\n" "$arg" >> "$WB_TEST_ARGS"; done\n',
        encoding="utf-8",
    )

    for embedded, expected in (("1", ["--no-open"]), ("0", [])):
        args_path = work / f"args-{embedded}"
        env = os.environ.copy()
        env.update({
            "ROOT": directory,
            "DO_UI": "1",
            "WB_SETUP_EMBEDDED": embedded,
            "WB_TEST_ARGS": str(args_path),
            "WB_TEST_HANDOFF": str(snippet),
        })
        master, slave = pty.openpty()
        try:
            subprocess.run(
                ["bash", "-c", 'step() { :; }; say() { :; }; . "$WB_TEST_HANDOFF"'],
                stdin=slave,
                stdout=slave,
                stderr=slave,
                env=env,
                check=True,
                timeout=10,
            )
        finally:
            os.close(slave)
            os.close(master)
        assert args_path.is_file(), f"bootstrap did not open the guide: embedded={embedded}"
        assert args_path.read_text(encoding="utf-8").splitlines() == expected, embedded
