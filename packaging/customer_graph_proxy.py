"""Owner-gated, read-only phone front for the VM-local Knowledge Graph.

The reviewed Glitch Cat engine keeps its own loopback listener on 4180. This
small front serves it on 4181, where Tailscale Serve can expose only an owner
session. It shares Fleetdeck's private capability and HMAC cookie contract.
"""

from __future__ import annotations

import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import os
from pathlib import Path
import re
import sys


def load_access():
    path = Path(__file__).with_name("fleetdeck-customer-access.py")
    spec = importlib.util.spec_from_file_location("customer_access", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Fleetdeck customer access helper is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


customer_access = load_access()
OWNER_ENTRY = re.compile(r"/p/([0-9a-f]{64})/graph\Z")
MAX_BODY = 16 * 1024 * 1024


class GraphProxyServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, *, backend_port: int = 4180):
        if address[0] != "127.0.0.1" or not 1 <= backend_port <= 65535:
            raise ValueError("graph proxy and engine must bind loopback")
        self.backend_port = backend_port
        super().__init__(address, GraphProxyHandler)


class GraphProxyHandler(BaseHTTPRequestHandler):
    server: GraphProxyServer
    server_version = "WidebandGraphProxy"
    sys_version = ""

    def log_message(self, _format, *_args):
        # The owner entry path carries a bearer capability.
        pass

    def reply(self, code: int, body: bytes = b"", content_type: str = "text/plain; charset=utf-8",
              *, headers: dict[str, str] | None = None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            return self.reply(200, b"ok\n")
        capability = customer_access.token()
        if not capability:
            return self.reply(403, b"forbidden\n")
        entry = OWNER_ENTRY.fullmatch(path)
        if entry:
            import hmac
            if not hmac.compare_digest(entry.group(1), capability):
                return self.reply(403, b"forbidden\n")
            return self.reply(303, headers={
                "Location": "/",
                "Set-Cookie": customer_access.cookie_header(capability),
            })
        if not customer_access.has_session(self.headers.get("Cookie"), capability):
            return self.reply(403, b"forbidden\n")
        if not self.path.startswith("/") or self.path.startswith("//"):
            return self.reply(400, b"invalid path\n")
        try:
            connection = http.client.HTTPConnection("127.0.0.1", self.server.backend_port,
                                                    timeout=10)
            try:
                connection.request(self.command, self.path)
                response = connection.getresponse()
                body = response.read(MAX_BODY + 1)
                if len(body) > MAX_BODY:
                    return self.reply(502, b"graph response too large\n")
                content_type = response.getheader("Content-Type") or "application/octet-stream"
                return self.reply(response.status, body, content_type)
            finally:
                connection.close()
        except (OSError, http.client.HTTPException):
            return self.reply(502, b"graph engine unavailable\n")

    def do_POST(self):
        # The graph engine is read-only. Close the connection without reusing a
        # request body, so a reverse proxy cannot misparse the next request.
        self.close_connection = True
        return self.reply(405, b"read-only graph\n")

    do_PUT = do_PATCH = do_DELETE = do_POST


def main() -> int:
    with GraphProxyServer(("127.0.0.1", 4181)) as server:
        server.serve_forever(poll_interval=0.25)
    return 0


if __name__ == "__main__":
    sys.exit(main())
