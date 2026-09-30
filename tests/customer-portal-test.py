#!/usr/bin/env python3
"""Isolated HTTP and storage checks for the bundled customer phone portal."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / "packaging/customer-portal.py"


class CustomerPortalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="wb-customer-portal-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.portal = self.root / "portal_server.py"
        shutil.copy2(SOURCE, self.portal)
        self.state = self.root / "state.json"
        self.status = self.root / "goal-status.json"
        self.notes = self.root / "notes-beta.json"
        self.token_file = self.root / "phone-access-token"
        self.token = "a" * 64
        self.prefix = "/p/" + self.token
        self.token_file.write_text(self.token + "\n", encoding="ascii")
        self.token_file.chmod(0o600)
        self.state.write_text(json.dumps({"metadata": {
            "os_name": "Aurora", "agent_name": "Orbit", "first_goal": "website",
            "head_session": "another-session",
        }}), encoding="utf-8")
        self.state.chmod(0o600)
        (self.root / "config.json").write_text(json.dumps({"ports": {"portal": 8790}}), encoding="utf-8")
        (self.root / "services.json").write_text('{"services": []}\n', encoding="utf-8")
        (self.root / "assets").mkdir()
        for size in (192, 512):
            (self.root / "assets" / f"icon-{size}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        patch = mock.patch.dict(os.environ, {
            "FLEETDECK_SETUP_STATE_PATH": str(self.state),
            "FLEETDECK_FIRST_GOAL_STATUS_PATH": str(self.status),
            "FLEETDECK_NOTES_PATH": str(self.notes),
            "FLEETDECK_ACCESS_TOKEN_PATH": str(self.token_file),
        })
        patch.start()
        self.addCleanup(patch.stop)
        spec = importlib.util.spec_from_file_location("customer_portal_test", self.portal)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.module.Handler)
        worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def raw_request(self, path: str, *, data: dict | None = None,
                    headers: dict | None = None, method: str = "GET") -> tuple[int, str]:
        body = json.dumps(data).encode() if data is not None else None
        request = urllib.request.Request(self.base + path, data=body, method=method,
                                         headers=headers or {})
        try:
            response = urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.read().decode("utf-8", errors="replace")

    def request(self, path: str, *, data: dict | None = None,
                headers: dict | None = None, method: str = "GET") -> tuple[int, str]:
        route = path if path == "/healthz" else self.prefix + path
        return self.raw_request(route, data=data, headers=headers, method=method)

    def test_full_fleetdeck_board_routes_and_mutation_boundary(self) -> None:
        self.assertEqual(self.request("/healthz"), (200, "ok\n"))
        with mock.patch.object(self.module, "head_session_present", return_value=False):
            pages = [self.request(route) for route in ("/", "/phone", "/board")]
        self.assertTrue(all(code == 200 for code, _ in pages))
        self.assertEqual(pages[0][1], pages[1][1])
        self.assertEqual(pages[1][1], pages[2][1])
        home = pages[0][1]
        for label in ("FLEETDECK", "Aurora", "Orbit", "First project",
                      "Knowledge Graph", "Live Terminal", "Messages", "Notes β"):
            self.assertIn(label.lower(), home.lower())
        for selector in ('class="board-head"', 'class="tile ', 'id="fleet-heading"',
                         'id="workspace-heading"', f'href="{self.prefix}/graph"',
                         f'href="{self.prefix}/watch"', f'href="{self.prefix}/notes"',
                         f'href="{self.prefix}/project"', 'data-service="agent"'):
            self.assertIn(selector, home)
        self.assertIn("3/5</b> ready", home)
        self.assertNotIn("http://127.0.0.1:4173", home)
        self.assertNotIn("brain" + "wave", home.lower())
        self.assertNotIn("/api/agent", home)
        self.assertNotIn("ttyd", home.lower())
        manifest = json.loads(self.request("/phone.webmanifest")[1])
        self.assertEqual(manifest["start_url"], self.prefix + "/board")
        self.assertEqual(manifest["scope"], self.prefix + "/")
        self.assertTrue(all(icon["src"].startswith(self.prefix + "/icon-")
                            for icon in manifest["icons"]))
        self.assertEqual(manifest["display"], "fullscreen")
        self.assertEqual(manifest["theme_color"], "#05070a")
        for route in ("/agent", "/graph", "/watch", "/notes"):
            self.assertEqual(self.request(route)[0], 200, route)
        code, graph = self.request("/graph")
        self.assertEqual(code, 200)
        self.assertIn('class="knowledge-graph"', graph)
        self.assertIn('class="edge"', graph)
        self.assertIn('data-node="head"', graph)
        self.assertIn('data-node="project"', graph)
        self.assertIn('addEventListener("keydown"', graph)
        self.assertIn("Messages listener", graph)
        self.assertEqual(self.request("/icon-192.png")[0], 200)
        self.assertEqual(self.module.onboarding_config()["head_session"], "wb-head")
        self.assertEqual(self.request("/api/watch")[0], 200)
        self.assertEqual(self.request("/t")[0], 404)
        self.assertEqual(self.request("/api/agent", data={}, method="POST")[0], 403)
        self.assertEqual(self.request("/api/route", data={}, method="POST")[0], 403)
        self.assertEqual(self.request("/api/board", data={}, method="POST")[0], 403)

    def test_capability_is_required_on_every_phone_route(self) -> None:
        for route in ("/", "/phone", "/board", "/agent", "/graph", "/watch",
                      "/notes", "/api/watch", "/api/board", "/api/notes",
                      "/phone.webmanifest", "/icon-192.png"):
            self.assertEqual(self.raw_request(route), (403, ""), route)
            self.assertEqual(self.raw_request("/p/" + "b" * 64 + route), (403, ""), route)
        self.assertEqual(self.raw_request("/p/" + self.token.upper() + "/board"), (403, ""))
        self.assertEqual(self.raw_request("/api/notes", data={"text": "secret"},
                                          method="POST"), (403, ""))
        self.assertEqual(self.raw_request("/p/" + "b" * 64 + "/api/notes",
                                          data={"text": "secret"}, method="POST"), (403, ""))
        self.assertFalse(self.notes.exists())
        self.assertIn(f'href="{self.prefix}/phone.webmanifest"',
                      self.request("/board")[1])
        self.assertIn(f'fetch("{self.prefix}/api/board"', self.request("/board")[1])
        self.assertIn(f'fetch("{self.prefix}/api/notes"', self.request("/notes")[1])
        with urllib.request.urlopen(self.base + self.prefix + "/board", timeout=3) as response:
            self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")

        self.token_file.chmod(0o644)
        self.assertEqual(self.request("/healthz")[0], 503)
        self.assertEqual(self.request("/board"), (403, ""))
        self.token_file.chmod(0o600)
        self.token_file.write_text("A" * 64, encoding="ascii")
        self.assertEqual(self.request("/healthz")[0], 503)
        self.assertEqual(self.request("/board"), (403, ""))
        self.token_file.unlink()
        target = self.root / "token-target"
        target.write_text(self.token, encoding="ascii")
        target.chmod(0o600)
        self.token_file.symlink_to(target)
        self.assertEqual(self.request("/healthz")[0], 503)
        self.assertEqual(self.request("/board"), (403, ""))

    def test_watch_captures_only_live_claude_pane(self) -> None:
        pane_line = "wb-head|1|1|%1|2.1.283|/Users/test/.local/bin/claude|1360|0\n"
        calls = []

        def running(command, **kwargs):
            calls.append(command)
            if command[:2] == ["tmux", "list-panes"]:
                return subprocess.CompletedProcess(command, 0, pane_line, "")
            if command[:2] == ["/bin/ps", "-p"]:
                return subprocess.CompletedProcess(
                    command, 0, "/Users/test/.local/bin/claude\n", "")
            if command[:2] == ["tmux", "capture-pane"]:
                return subprocess.CompletedProcess(command, 0, "agent output\n", "")
            raise AssertionError(command)

        with mock.patch.object(self.module, "verified_tmux", return_value="tmux"), \
             mock.patch.object(self.module.subprocess, "run", side_effect=running):
            self.assertEqual(json.loads(self.request("/api/watch")[1]),
                             {"running": True, "text": "agent output\n"})
        self.assertEqual(len([call for call in calls if call[:2] == ["tmux", "capture-pane"]]), 1)
        self.assertEqual(calls[0][4], "wb-head")

        def shell(command, **kwargs):
            if command[:2] == ["tmux", "list-panes"]:
                return subprocess.CompletedProcess(
                    command, 0, "wb-head|1|1|%1|zsh|/bin/zsh|1360|0\n", "")
            raise AssertionError("shell output must never be captured")

        with mock.patch.object(self.module, "verified_tmux", return_value="tmux"), \
             mock.patch.object(self.module.subprocess, "run", side_effect=shell):
            self.assertEqual(json.loads(self.request("/api/watch")[1]),
                             {"running": False, "text": ""})
            self.assertFalse(self.module.head_session_present("wb-head"))

        def wrong_session(command, **kwargs):
            if command[:2] == ["tmux", "list-panes"]:
                return subprocess.CompletedProcess(
                    command, 0, pane_line.replace("wb-head|", "wb-head-other|"), "")
            raise AssertionError("another session must never be captured")

        with mock.patch.object(self.module, "verified_tmux", return_value="tmux"), \
             mock.patch.object(self.module.subprocess, "run", side_effect=wrong_session):
            self.assertEqual(json.loads(self.request("/api/watch")[1]),
                             {"running": False, "text": ""})

    def test_watch_resolves_tmux_without_ambient_fallback(self) -> None:
        private_bin = self.root / "private" / "bin"
        private_bin.mkdir(parents=True)
        tmux = private_bin / "tmux"
        tmux.write_text("tmux")
        answer = subprocess.CompletedProcess([], 0, str(tmux) + "\n", "")
        with mock.patch.object(self.module.subprocess, "run", return_value=answer) as resolve:
            self.assertEqual(self.module.verified_tmux(), str(tmux))
        resolve.assert_called_once_with([str(self.module.TOOLCHAIN_RESOLVER), "tmux"],
                                        capture_output=True, text=True, timeout=15)
        with mock.patch.object(self.module.subprocess, "run", return_value=
                               subprocess.CompletedProcess([], 1, "", "unavailable")):
            self.assertIsNone(self.module.verified_tmux())
            self.assertIsNone(self.module.active_head_pane("wb-head"))

    def test_board_status_uses_only_verified_local_facts(self) -> None:
        with mock.patch.object(self.module, "head_session_present", return_value=True), \
             mock.patch.object(self.module, "project_link",
                               return_value=("https://agent.example.ts.net:4173/", True)):
            code, body = self.request("/api/board")
            self.assertEqual(code, 200)
            self.assertEqual(json.loads(body), {
                "head_session_present": True,
                "project_url": "https://agent.example.ts.net:4173/",
                "project_local": True,
            })
            home = self.request("/board")[1]
        self.assertIn('href="https://agent.example.ts.net:4173/"', home)
        self.assertIn("5/5</b> ready", home)
        self.assertNotIn("terminal text", body)

        self.state.write_text(json.dumps({"metadata": {
            "os_name": "<script>alert(1)</script>", "agent_name": 'Orbit"><img src=x>',
            "first_goal": "website", "first_project_url": "https://unverified.example/",
        }}), encoding="utf-8")
        self.state.chmod(0o600)
        with mock.patch.object(self.module, "head_session_present", return_value=False):
            home = self.request("/board")[1]
            graph = self.request("/graph")[1]
        self.assertNotIn("<script>alert(1)</script>", home)
        self.assertNotIn('Orbit"><img', home)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", home)
        self.assertNotIn("https://unverified.example/", home)
        self.assertNotIn("<script>alert(1)</script>", graph)
        self.assertNotIn('Orbit"><img', graph)

    def test_notes_beta_is_private_concurrent_and_csrf_guarded(self) -> None:
        payload = {"title": "A thought", "text": "Build the first thing"}
        self.assertEqual(self.request("/api/notes", data=payload, method="POST",
                                      headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("/api/notes", data=payload, method="POST",
                                      headers={"Content-Type": "application/json",
                                               "Origin": "https://other.example"})[0], 403)
        self.assertFalse(self.notes.exists())
        headers = {"Content-Type": "application/json", "Origin": self.base}
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda i: self.request("/api/notes", data={
                "title": f"Note {i}", "text": f"Idea {i}"}, method="POST", headers=headers),
                                    range(20)))
        self.assertTrue(all(code == 200 for code, _ in results))
        self.assertEqual(len(json.loads(self.request("/api/notes")[1])["notes"]), 20)
        self.assertEqual(self.notes.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.notes.parent.stat().st_mode & 0o777, 0o700)

        for i in range(8):
            self.module.add_note({"title": f"Large {i}", "text": "x" * 11000})
        self.assertGreater(self.notes.stat().st_size, 64 * 1024)
        self.assertEqual(len(self.module.read_notes()), 28)
        with self.notes.open("r+b") as stream:
            stream.truncate(self.module.NOTES_FILE_MAX + 1)
        with self.assertRaises(ValueError):
            self.module.read_notes()

    def test_first_project_requires_page_and_current_verified_route(self) -> None:
        class Site(BaseHTTPRequestHandler):
            root_ready = True

            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path == "/health":
                    body, mime, code = b'{"service":"wideband-first-project"}', "application/json", 200
                elif self.path == "/" and self.root_ready:
                    body, mime, code = b"<!doctype html><title>Project</title>", "text/html", 200
                else:
                    body, mime, code = b"missing", "text/plain", 404
                self.send_response(code)
                self.send_header("Content-Type", mime)
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Site)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = server.server_port
        self.status.write_text(json.dumps({"goal": "website", "os_name": "Aurora",
                                           "agent_name": "Orbit", "status": "ready", "port": port,
                                           "phone_url": "https://test.tailnet.ts.net:4173/"}), encoding="utf-8")
        self.status.chmod(0o600)
        (self.root / "services.json").write_text(json.dumps({"services": [{
            "id": "first-project", "source": "wideband-first-goal", "port": port}]}), encoding="utf-8")
        with mock.patch.object(self.module, "live_serve_url", return_value="https://test.tailnet.ts.net:4173/"):
            self.assertEqual(self.module.project_link(self.module.onboarding_config())[0],
                             "https://test.tailnet.ts.net:4173/")
        with mock.patch.object(self.module, "live_serve_url", return_value=""):
            self.assertEqual(self.module.project_link(self.module.onboarding_config()), ("", True))
        Site.root_ready = False
        with mock.patch.object(self.module, "live_serve_url", return_value="https://test.tailnet.ts.net:4173/"):
            self.assertEqual(self.module.project_link(self.module.onboarding_config()), ("", False))

    def test_live_serve_lookup_uses_cli_mode(self) -> None:
        port = 4173
        dns = "agent.example.ts.net"
        serve = {"TCP": {str(port): {"HTTPS": True}}, "Web": {
            f"{dns}:{port}": {"Handlers": {"/": {"Proxy": f"http://127.0.0.1:{port}"}}}}}
        replies = [subprocess.CompletedProcess([], 0, json.dumps(serve), ""),
                   subprocess.CompletedProcess([], 0, json.dumps({"Self": {"DNSName": dns + "."}}), "")]
        with mock.patch.object(self.module.os, "access", return_value=True), \
             mock.patch.object(self.module.subprocess, "run", side_effect=replies) as ts_run:
            self.assertEqual(self.module.live_serve_url(port), f"https://{dns}:{port}")
        self.assertEqual(len(ts_run.call_args_list), 2)
        self.assertTrue(all(call.kwargs["env"]["TAILSCALE_BE_CLI"] == "1"
                            for call in ts_run.call_args_list))


if __name__ == "__main__":
    unittest.main()
