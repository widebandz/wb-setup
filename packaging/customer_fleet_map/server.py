"""Capability-gated, read-only HTTP front for the local terminal network."""

from __future__ import annotations

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import urlsplit

from .reader import FleetMapCache


TOKEN = re.compile(r"[0-9a-f]{64}\Z")
PROTECTED = re.compile(r"/p/([0-9a-f]{64})(/.*)?\Z")
PACKAGE = Path(__file__).resolve().parent
DEFAULT_TOKEN_PATH = Path("~/.wideband/fleetdeck/phone-access-token").expanduser()


def read_access_token(path: Path) -> str | None:
    """Read the same owner-only capability used by the Fleetdeck phone board."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o777 != 0o600 or info.st_size > 65):
                return None
            raw = stream.read(66)
        value = raw.removesuffix(b"\n").decode("ascii")
        return value if TOKEN.fullmatch(value) else None
    except (OSError, UnicodeError):
        return None


def render_page(prefix: str) -> bytes:
    """Resolve only the map's own page and API paths under a checked token."""
    if not re.fullmatch(r"/p/[0-9a-f]{64}", prefix):
        raise ValueError("invalid map capability prefix")
    page = (PACKAGE / "page.html").read_text(encoding="utf-8")
    if page.count("__FLEET_MAP_PAGE__") != 2 or page.count("__FLEET_MAP_API__") != 1:
        raise RuntimeError("map page route contract changed")
    return (page.replace("__FLEET_MAP_PAGE__", prefix + "/fleet-map")
                .replace("__FLEET_MAP_API__", prefix + "/api/fleet-map").encode("utf-8"))


def board_origin(value: str) -> str | None:
    """Allow framing only by this Mac's exact tailnet or loopback board."""
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (parsed.username or parsed.password or parsed.path or parsed.query
            or parsed.fragment or port != 8790):
        return None
    if parsed.scheme == "http" and parsed.hostname == "wideband.localhost":
        return "http://wideband.localhost:8790"
    if (parsed.scheme == "https" and parsed.hostname
            and parsed.hostname.endswith(".ts.net")):
        return f"https://{parsed.hostname}:8790"
    return None


class MapServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, *, access_path: Path = DEFAULT_TOKEN_PATH,
                 board_url: str = "", cache: FleetMapCache | None = None):
        host, _port = address
        if host != "127.0.0.1":
            raise ValueError("fleet map must bind loopback")
        self.access_path = access_path
        self.board_origin = board_origin(board_url) if board_url else None
        if board_url and self.board_origin is None:
            raise ValueError("invalid Fleetdeck board origin")
        self.cache = cache or FleetMapCache()
        super().__init__(address, MapHandler)


class MapHandler(BaseHTTPRequestHandler):
    server: MapServer
    server_version = "WidebandFleetMap"
    sys_version = ""

    def log_message(self, _format, *_args):
        # Request paths contain the bearer capability. Never print them.
        pass

    def _send(self, code: int, body: bytes, content_type: str = "text/plain; charset=utf-8",
              *, csp: str | None = None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        if csp:
            self.send_header("Content-Security-Policy", csp)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _route(self) -> tuple[str, str] | None:
        try:
            path = urlsplit(self.path).path
        except ValueError:
            return None
        match = PROTECTED.fullmatch(path)
        expected = read_access_token(self.server.access_path)
        if not match or expected is None or not hmac.compare_digest(match.group(1), expected):
            return None
        return match.group(2) or "/", "/p/" + expected

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if self.path == "/healthz":
            return self._send(200, b"ok\n")
        if (self.server.board_origin == "http://wideband.localhost:8790"
                and self.headers.get("Host") != f"wideband.localhost:{self.server.server_port}"):
            return self._send(403, b"")
        route = self._route()
        if route is None:
            return self._send(403, b"")
        path, prefix = route
        if path == "/fleet-map":
            ancestors = "'self'"
            if self.server.board_origin:
                ancestors += " " + self.server.board_origin
            csp = ("default-src 'none'; script-src 'unsafe-inline'; "
                   "style-src 'unsafe-inline'; connect-src 'self'; "
                   "base-uri 'none'; form-action 'none'; frame-ancestors "
                   + ancestors)
            try:
                body = render_page(prefix)
            except (OSError, RuntimeError):
                return self._send(503, b"map unavailable\n")
            return self._send(200, body, "text/html; charset=utf-8", csp=csp)
        if path == "/api/fleet-map":
            code, snapshot = self.server.cache.get()
            body = json.dumps(snapshot, ensure_ascii=False,
                              separators=(",", ":")).encode("utf-8")
            return self._send(code, body, "application/json")
        return self._send(404, b"")

    def do_POST(self):
        if (self.server.board_origin == "http://wideband.localhost:8790"
                and self.headers.get("Host") != f"wideband.localhost:{self.server.server_port}"):
            return self._send(403, b"")
        if self._route() is None:
            return self._send(403, b"")
        return self._send(405, b"read-only map\n")

    do_PUT = do_PATCH = do_DELETE = do_POST


def main() -> int:
    bind = os.environ.get("FLEETDECK_FLEET_MAP_BIND", "127.0.0.1")
    port = int(os.environ.get("FLEETDECK_FLEET_MAP_PORT", "18790"))
    access_path = Path(os.environ.get("FLEETDECK_ACCESS_TOKEN_PATH",
                                      str(DEFAULT_TOKEN_PATH))).expanduser()
    with MapServer((bind, port), access_path=access_path,
                   board_url=os.environ.get("FLEETDECK_BOARD_ORIGIN", "")) as server:
        server.serve_forever(poll_interval=0.25)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
