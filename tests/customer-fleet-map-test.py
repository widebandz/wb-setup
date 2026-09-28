#!/usr/bin/env python3
"""Read-only map boundary and local fleet collection contract."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
import urllib.error
import urllib.request
import uuid

PACKAGING = Path(__file__).resolve().parents[1] / "packaging"
sys.path.insert(0, str(PACKAGING))

from customer_fleet_map import SnapshotError, validate_snapshot  # noqa: E402
from customer_fleet_map import reader  # noqa: E402
from customer_fleet_map.server import MapServer  # noqa: E402


TOKEN = "a" * 64
STAMP = "2026-09-28T00:00:00Z"


def snapshot():
    return {
        "schema_version": "agent-fleet.snapshot.v1", "collected_at": STAMP,
        "nodes": [{"id": "host:sample", "type": "host", "label": "Sample Mac",
                   "parent_id": None, "declared": True, "observed": True,
                   "source_refs": ["tmux"], "observed_at": STAMP},
                  {"id": "session:wb-head", "type": "session", "label": "wb-head",
                   "parent_id": "host:sample", "declared": True, "observed": True,
                   "source_refs": ["tmux"], "observed_at": STAMP}],
        "edges": [], "summary": {"live_sessions": 1, "source_health": "complete"},
        "sources": [{"id": "tmux", "status": "available", "as_of": STAMP}],
        "unknowns": [],
    }


class Cache:
    def get(self):
        return 200, validate_snapshot(snapshot()) | {"status": "fresh"}


class MapServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.token_path = Path(self.temp.name) / "phone-access-token"
        self.token_path.write_text(TOKEN + "\n", encoding="ascii")
        self.token_path.chmod(0o600)
        self.server = MapServer(("127.0.0.1", 0), access_path=self.token_path,
                                board_url="https://sample-device.tailabc.ts.net:8790",
                                cache=Cache())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.base = "http://127.0.0.1:{}".format(self.server.server_port)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, path, method="GET"):
        req = urllib.request.Request(self.base + path, method=method)
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, exc.headers, exc.read()

    def test_capability_keeps_page_and_api_private(self):
        status, _, body = self.request("/healthz")
        self.assertEqual((status, body), (200, b"ok\n"))
        for path in ("/fleet-map", "/api/fleet-map", "/p/" + "b" * 64 + "/fleet-map",
                     "/p/" + "b" * 64 + "/api/fleet-map"):
            self.assertEqual(self.request(path)[0], 403)

        prefix = "/p/" + TOKEN
        status, headers, page = self.request(prefix + "/fleet-map")
        self.assertEqual(status, 200)
        self.assertIn(b"Live terminal network", page)
        self.assertIn((prefix + "/api/fleet-map").encode(), page)
        self.assertNotIn(b'fetch("/api/fleet-map"', page)
        self.assertNotIn(b".ts.net", page.lower())
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        self.assertIn("connect-src 'self'", headers["Content-Security-Policy"])
        self.assertIn("https://sample-device.tailabc.ts.net:8790",
                      headers["Content-Security-Policy"])
        status, _, body = self.request(prefix + "/api/fleet-map")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["nodes"][1]["label"], "wb-head")
        self.assertEqual(self.request(prefix + "/api/chats")[0], 404)
        self.assertEqual(self.request(prefix + "/api/fleet-map", method="POST")[0], 405)
        self.assertEqual(self.request(prefix + "/fleet-map", method="DELETE")[0], 405)

    def test_token_file_must_be_private_regular_file(self):
        prefix = "/p/" + TOKEN + "/fleet-map"
        self.token_path.chmod(0o644)
        self.assertEqual(self.request(prefix)[0], 403)
        self.token_path.unlink()
        other = Path(self.temp.name) / "actual-token"
        other.write_text(TOKEN, encoding="ascii")
        other.chmod(0o600)
        self.token_path.symlink_to(other)
        self.assertEqual(self.request(prefix)[0], 403)

    def test_rejects_non_loopback_and_unreviewed_frame_origin(self):
        with self.assertRaises(ValueError):
            MapServer(("0.0.0.0", 0), access_path=self.token_path, cache=Cache())
        with self.assertRaises(ValueError):
            MapServer(("127.0.0.1", 0), access_path=self.token_path,
                      board_url="https://example.com:8790", cache=Cache())


class CollectorTests(unittest.TestCase):
    def test_private_metadata_is_rejected_before_browser_projection(self):
        for label in ("someone@example.com", "/Users/sample/private", "+15551234567"):
            with self.subTest(label=label):
                raw = snapshot()
                raw["nodes"][1]["label"] = label
                with self.assertRaises(SnapshotError):
                    validate_snapshot(raw)

    def test_bundled_collector_uses_only_an_isolated_tmux_socket(self):
        with tempfile.TemporaryDirectory() as home:
            env = os.environ.copy()
            env.update(HOME=home, TM_TMUX_SOCKET="wb-map-test-" + uuid.uuid4().hex,
                       TM_SESSIONS_CONF=str(Path(home) / "sessions.conf"),
                       FLEETDECK_FLEET_HOST_ID="local")
            completed = subprocess.run(
                [sys.executable, str(PACKAGING / "customer_fleet_map" / "snapshot.py"),
                 "--host-id", "sample", "--json"], env=env, capture_output=True,
                text=True, timeout=15, check=True)
            raw = json.loads(completed.stdout)
            safe = validate_snapshot(raw)
            self.assertEqual(safe["schema_version"], "agent-fleet.snapshot.v1")
            self.assertEqual([n["id"] for n in safe["nodes"] if n["type"] == "host"],
                             ["host:sample"])
            self.assertFalse(any(n["type"] == "session" and n["observed"] is True
                                 for n in safe["nodes"]))
            self.assertNotIn(home, completed.stdout)
            with mock.patch.dict(os.environ, env):
                projected = validate_snapshot(reader.collect_local_snapshot())
            self.assertEqual(projected["nodes"][0]["id"], "host:local")
            self.assertFalse(any(n["type"] == "session" and n["observed"] is True
                                 for n in projected["nodes"]))


if __name__ == "__main__":
    unittest.main()
