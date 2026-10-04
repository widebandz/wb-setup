#!/usr/bin/env python3
"""Exercise the packaged Terminal-to-guide gate in an isolated home."""

import os
import pathlib
import pty
import shutil
import subprocess
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]


def run(home: pathlib.Path, entry: pathlib.Path, *, terminal: bool = True,
        extra: dict[str, str] | None = None, arguments: tuple[str, ...] = ()) -> int:
    env = os.environ.copy()
    env.update({"HOME": str(home), "WB_TEST_EVENTS": str(home / "events")})
    env.update(extra or {})
    if terminal:
        master, slave = pty.openpty()
        try:
            result = subprocess.run(["/bin/bash", str(entry), *arguments], env=env, stdin=slave,
                                    stdout=slave, stderr=slave, timeout=20)
        finally:
            os.close(slave)
            os.close(master)
    else:
        result = subprocess.run(["/bin/bash", str(entry), *arguments], env=env,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=20)
    return result.returncode


with tempfile.TemporaryDirectory(prefix="wb-client-cli-") as temp:
    home = pathlib.Path(temp) / "home"
    payload = pathlib.Path(temp) / "payload"
    state = home / ".wideband" / "setup"
    lib = payload / "lib"
    state.mkdir(parents=True)
    lib.mkdir(parents=True)
    shutil.copy2(ROOT / "packaging" / "run-setup.command", payload / "run-setup.command")
    entry = payload / "run-setup.command"
    (state / "client-package").write_text("build-a\n")
    (lib / "bootstrap-homebrew.sh").write_text(
        'wb_tc_resolve() { WB_TOOLCHAIN_KIND=private; '
        'WB_TOOLCHAIN_BUILD_ID="${WB_TEST_TOOL_BUILD:-$(sed -n 1p "$HOME/.wideband/setup/client-package")}"; '
        '[ -f "$HOME/.sop-vars" ]; }\n'
        'wb_tc_private_bin() { [ "${WB_FAIL_TOOL:-}" != "$1" ]; }\n')
    (lib / "toolchain-path").write_text(
        '#!/bin/bash\n[ "${WB_FAIL_TOOL:-}" != "$1" ] || exit 1\n'
        'case "$1" in python3|node|tmux|ttyd|imsg) echo /usr/bin/true;; *) exit 2;; esac\n')
    (lib / "toolchain-path").chmod(0o755)
    (payload / "bootstrap.sh").write_text(
        '#!/bin/bash\nprintf "bootstrap\\n" >> "$WB_TEST_EVENTS"\n'
        '[ "${WB_FAIL_BOOTSTRAP:-0}" != 1 ] || { '
        'printf "needs_attention\\n" > "$HOME/.wideband/setup/bootstrap-status"; exit 1; }\n'
        'printf "export ORG=wideband\\n" > "$HOME/.sop-vars"\n'
        'printf "ready\\n" > "$HOME/.wideband/setup/bootstrap-status"\n')
    engine = payload / ".wideband-setup-engine"
    engine.write_text(
        '#!/bin/bash\nprintf "engine\\n" >> "$WB_TEST_EVENTS"\n'
        'printf "%s\\n" "$*" > "$HOME/engine-arguments"\n')
    engine.chmod(0o755)

    assert run(home, entry, extra={"WB_FAIL_BOOTSTRAP": "1"}) != 0
    assert (home / "events").read_text().splitlines() == ["bootstrap"]
    assert not (state / "cli-ready-build").exists()

    (home / "events").unlink()
    assert run(home, entry, extra={"WB_FAIL_TOOL": "tmux"}) != 0
    assert (home / "events").read_text().splitlines() == ["bootstrap"]
    assert not (state / "cli-ready-build").exists()

    (home / "events").unlink()
    assert run(home, entry, extra={"WB_TEST_TOOL_BUILD": "old-build"}) != 0
    assert (home / "events").read_text().splitlines() == ["bootstrap"]
    assert not (state / "cli-ready-build").exists()

    (home / "events").unlink()
    assert run(home, entry) == 0
    assert (home / "events").read_text().splitlines() == ["bootstrap", "engine"]
    assert (state / "cli-ready-build").read_text() == "build-a\n"
    assert (state / "cli-ready-build").stat().st_mode & 0o777 == 0o600

    (home / "events").unlink()
    assert run(home, entry, terminal=False) == 0
    assert (home / "events").read_text().splitlines() == ["engine"]
    assert run(home, entry, terminal=False, arguments=("--embedded",)) == 0
    assert (home / "engine-arguments").read_text() == "--no-open\n"

    (state / "client-package").write_text("build-b\n")
    (home / "events").unlink()
    assert run(home, entry, terminal=False) != 0
    assert not (home / "events").exists()
    assert run(home, entry) == 0
    assert (home / "events").read_text().splitlines() == ["bootstrap", "engine"]
    assert (state / "cli-ready-build").read_text() == "build-b\n"

    (state / "cli-ready-build").unlink()
    (state / "other-file").write_text("build-b\n")
    (state / "cli-ready-build").symlink_to(state / "other-file")
    (home / "events").unlink()
    assert run(home, entry, terminal=False) != 0
    assert not (home / "events").exists()

print("packaged CLI gate: fail closed, verify tools, open UI after success, resume by build")
