#!/usr/bin/env python3
"""Exercise the owner gate and real HTTP forwarding around a local graph."""

import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "customer_graph_proxy", ROOT / "packaging" / "customer_graph_proxy.py")
graph = importlib.util.module_from_spec(spec)
spec.loader.exec_module(graph)
stack_spec = importlib.util.spec_from_file_location(
    "phone_stack", ROOT / "packaging" / "phone-stack.py")
stack = importlib.util.module_from_spec(stack_spec)
stack_spec.loader.exec_module(stack)
TOKEN = "a" * 64


class Engine(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *_args):
        pass

    def do_GET(self):
        self.calls.append(self.path)
        if self.path == "/api/stats":
            body = json.dumps({"nodes": 3, "edges": 2}).encode()
            mime = "application/json"
        elif self.path == "/api/graph?lens=surface":
            body = json.dumps({"nodes": [{"id": "vm"}], "edges": [{"from": "vm"}]}).encode()
            mime = "application/json"
        else:
            body = "<title>Wideband — knowledge graph</title>".encode()
            mime = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class GraphProxyTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="wb-graph-proxy-")
        self.addCleanup(temporary.cleanup)
        token_path = Path(temporary.name) / "phone-access-token"
        token_path.write_text(TOKEN + "\n", encoding="ascii")
        token_path.chmod(0o600)
        environment = mock.patch.dict(os.environ, {"FLEETDECK_ACCESS_TOKEN_PATH": str(token_path)})
        environment.start()
        self.addCleanup(environment.stop)
        Engine.calls = []
        backend = ThreadingHTTPServer(("127.0.0.1", 0), Engine)
        self.addCleanup(backend.server_close)
        self.addCleanup(backend.shutdown)
        backend_thread = threading.Thread(target=backend.serve_forever, daemon=True)
        backend_thread.start()
        front = graph.GraphProxyServer(("127.0.0.1", 0), backend_port=backend.server_port)
        self.addCleanup(front.server_close)
        self.addCleanup(front.shutdown)
        front_thread = threading.Thread(target=front.serve_forever, daemon=True)
        front_thread.start()
        self.port = front.server_port

    def request(self, path, *, method="GET", cookie=""):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            headers = {"Cookie": cookie} if cookie else {}
            connection.request(method, path, headers=headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_unauthorized_graph_and_api_never_reach_engine(self):
        for path in ("/", "/api/stats", "/api/graph?lens=surface",
                     "/p/" + "b" * 64 + "/graph"):
            self.assertEqual(self.request(path)[0], 403)
        self.assertEqual(Engine.calls, [])
        self.assertEqual(self.request("/healthz")[0], 200)

    def test_owner_entry_fetches_real_local_graph_data_and_refuses_writes(self):
        status, headers, _ = self.request(f"/p/{TOKEN}/graph")
        self.assertEqual(status, 303)
        self.assertEqual(headers["Location"], "/")
        self.assertIn("Secure; HttpOnly; SameSite=Strict", headers["Set-Cookie"])
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        status, _headers, body = self.request("/api/stats", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"nodes": 3, "edges": 2})
        status, _headers, body = self.request("/api/graph?lens=surface", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["nodes"][0]["id"], "vm")
        self.assertEqual(self.request("/", cookie=cookie)[0], 200)
        self.assertEqual(self.request("/api/stats", method="POST", cookie=cookie)[0], 405)
        self.assertEqual(Engine.calls, ["/api/stats", "/api/graph?lens=surface", "/"])

    def test_serve_migrates_only_the_prior_graph_engine_mapping(self):
        host = "customer.example.ts.net"
        target = "http://127.0.0.1:4180"
        commands = []

        def run(*args, **_kwargs):
            nonlocal target
            commands.append(args[1:])
            if args[1:] == ("serve", "status", "--json"):
                status = {"Web": {f"{host}:8792": {"Handlers": {"/": {"Proxy": target}}}},
                          "TCP": {"8792": {"HTTPS": True}}}
                return subprocess.CompletedProcess(args, 0, json.dumps(status), "")
            if args[1:3] == ("serve", "--bg"):
                target = args[-1]
                return subprocess.CompletedProcess(args, 0, "", "")
            raise AssertionError(args)

        with mock.patch.object(stack, "call", side_effect=run):
            stack.ensure_serve(host, 8792, 4181, previous_local_port=4180)
            self.assertEqual(target, "http://127.0.0.1:4181")
            target = "http://127.0.0.1:9999"
            before = len(commands)
            with self.assertRaisesRegex(ValueError, "different owner"):
                stack.ensure_serve(host, 8792, 4181, previous_local_port=4180)
            self.assertEqual(commands[before:], [("serve", "status", "--json")])

    def test_graph_tile_migrates_from_engine_to_owner_gate_only(self):
        with tempfile.TemporaryDirectory(prefix="wb-graph-registry-") as directory:
            fleetdeck = Path(directory)
            registry = fleetdeck / "services.json"
            original = {"groups": [{"id": "fleet", "label": "Fleet"}],
                        "services": [{"id": "graph", "group": "fleet", "port": 4180,
                                      "source": "wideband-phone-stack", "name": "Client title"}]}
            registry.write_text(json.dumps(original))
            desired = {"id": "graph", "group": "fleet", "port": 4181,
                       "name": "Knowledge Graph"}
            with mock.patch.object(stack, "FD", fleetdeck):
                stack.register_service(desired)
                migrated = json.loads(registry.read_text())
                self.assertEqual(migrated["services"][0]["port"], 4181)
                self.assertEqual(migrated["services"][0]["name"], "Client title")
                stack.register_service(desired)
                self.assertEqual(json.loads(registry.read_text()), migrated)
                migrated["services"][0]["port"] = 9999
                registry.write_text(json.dumps(migrated))
                with self.assertRaisesRegex(ValueError, "another entry"):
                    stack.register_service(desired)
                self.assertEqual(json.loads(registry.read_text())["services"][0]["port"], 9999)


if __name__ == "__main__":
    unittest.main()
