"""Private phone capability shared by the customer Fleetdeck surfaces."""

from __future__ import annotations

import hashlib
import hmac
from http.cookies import SimpleCookie
import os
from pathlib import Path
import re
import stat


COOKIE_NAME = "wb_fleetdeck_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30


def token_path() -> Path:
    return Path(os.environ.get(
        "FLEETDECK_ACCESS_TOKEN_PATH",
        "~/.wideband/fleetdeck/phone-access-token")).expanduser()


def token() -> str | None:
    """Read this owner's 256-bit capability from a regular private file only."""
    try:
        fd = os.open(token_path(), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_nlink != 1 or info.st_mode & 0o077
                    or info.st_size not in (64, 65)):
                return None
            raw = os.read(fd, 66)
            if raw.endswith(b"\n"):
                raw = raw[:-1]
            if len(raw) != 64:
                return None
            value = raw.decode("ascii")
        finally:
            os.close(fd)
    except (OSError, UnicodeError, RuntimeError):
        return None
    return value if re.fullmatch(r"[0-9a-f]{64}", value) else None


def session_value(capability: str) -> str:
    """Derive a cookie proof; the raw capability never becomes a cookie."""
    return hmac.new(bytes.fromhex(capability), b"wideband-fleetdeck-session-v1",
                    hashlib.sha256).hexdigest()


def local_http_request(host: str | None, port: int) -> bool:
    """Permit a host-only cookie only on the dedicated local preview name."""
    return (os.environ.get("FLEETDECK_LOCAL_ONLY") == "1"
            and host == f"wideband.localhost:{port}")


def same_origin_post(origin: str | None, host: str | None, port: int) -> bool:
    if not host or not origin:
        return False
    scheme = "http" if local_http_request(host, port) else "https"
    return origin == f"{scheme}://{host}"


def cookie_header(capability: str, *, secure: bool = True) -> str:
    flags = "Secure; " if secure else ""
    return (f"{COOKIE_NAME}={session_value(capability)}; Path=/; "
            f"Max-Age={COOKIE_MAX_AGE}; {flags}HttpOnly; SameSite=Strict")


def has_session(cookie: str | None, capability: str) -> bool:
    try:
        jar = SimpleCookie()
        jar.load(cookie or "")
        value = jar.get(COOKIE_NAME)
        return bool(value) and hmac.compare_digest(value.value, session_value(capability))
    except (ValueError, TypeError):
        return False
