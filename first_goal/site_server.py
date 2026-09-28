#!/usr/bin/env python3
"""Small loopback preview server for the first Wideband website."""

from __future__ import annotations

import argparse
import http.server
import json
from pathlib import Path


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: str, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path == "/health":
            body = json.dumps({"status": "ready", "service": "wideband-first-project"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def list_directory(self, path: str):
        self.send_error(404, "No directory listing")
        return None

    def translate_path(self, path: str) -> str:
        translated = super().translate_path(path)
        root = Path(self.directory).resolve()
        candidate = Path(translated).resolve()
        if not candidate.is_relative_to(root):
            return str(root / "__not_found__")
        if any(part.startswith(".") for part in candidate.relative_to(root).parts):
            return str(root / "__not_found__")
        return str(candidate)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    directory = Path(args.directory).resolve(strict=True)
    if not directory.is_dir() or not 1024 <= args.port <= 65535:
        parser.error("an existing directory and unprivileged port are required")
    handler = lambda *a, **kw: Handler(*a, directory=str(directory), **kw)
    with http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
