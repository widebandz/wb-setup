#!/usr/bin/env python3
"""Create or verify the private capability for the customer phone board.

The token is never printed.  It lives outside the managed Fleetdeck source so
a portal upgrade cannot replace it or invalidate a saved phone home-screen app.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import secrets
import stat
import sys


TOKEN_NAME = "phone-access-token"
TOKEN_PATTERN = re.compile(rb"[0-9a-f]{64}")
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
FILE_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def private_child(parent_fd: int, name: str) -> int:
    try:
        os.mkdir(name, mode=0o700, dir_fd=parent_fd)
    except FileExistsError:
        pass
    fd = os.open(name, DIR_FLAGS, dir_fd=parent_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("phone access directory has unsafe ownership or type")
        os.fchmod(fd, 0o700)
        return fd
    except Exception:
        os.close(fd)
        raise


def ensure_token(home: Path) -> None:
    home_fd = os.open(home, DIR_FLAGS)
    try:
        wideband_fd = private_child(home_fd, ".wideband")
        try:
            fleetdeck_fd = private_child(wideband_fd, "fleetdeck")
            try:
                try:
                    fd = os.open(TOKEN_NAME,
                                 os.O_WRONLY | os.O_CREAT | os.O_EXCL | FILE_NOFOLLOW,
                                 0o600, dir_fd=fleetdeck_fd)
                except FileExistsError:
                    fd = os.open(TOKEN_NAME, os.O_RDONLY | FILE_NOFOLLOW,
                                 dir_fd=fleetdeck_fd)
                    with os.fdopen(fd, "rb") as token_file:
                        info = os.fstat(token_file.fileno())
                        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600
                                or info.st_size != 64
                                or not TOKEN_PATTERN.fullmatch(token_file.read(65))):
                            raise ValueError("existing phone access token is unsafe")
                    return
                try:
                    token = secrets.token_hex(32).encode("ascii")
                    with os.fdopen(fd, "wb") as token_file:
                        token_file.write(token)
                        token_file.flush()
                        os.fsync(token_file.fileno())
                except Exception:
                    os.unlink(TOKEN_NAME, dir_fd=fleetdeck_fd)
                    raise
            finally:
                os.close(fleetdeck_fd)
        finally:
            os.close(wideband_fd)
    finally:
        os.close(home_fd)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: phone-access-token.py HOME", file=sys.stderr)
        return 2
    try:
        ensure_token(Path(sys.argv[1]))
    except (OSError, ValueError) as error:
        print(f"Wideband phone access: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
