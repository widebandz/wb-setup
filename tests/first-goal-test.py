#!/usr/bin/env python3
"""Isolated first-job tests; no host LaunchAgents or Tailscale changes."""

from __future__ import annotations

import json
import io
import os
import importlib.util
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "first_goal" / "runner.py"
SERVER = ROOT / "first_goal" / "site_server.py"
spec = importlib.util.spec_from_file_location("first_goal_runner", RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def free_preview_port() -> int:
    for port in range(4173, 4200):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("no free first-project test port")


class FirstGoalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="wb-first-goal-")
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.env = os.environ | {
            "HOME": str(self.home),
            "WB_FIRST_GOAL_SKIP_LAUNCHD": "1",
        }
        self.state = self.home / ".wideband/setup/state.json"
        self.state.parent.mkdir(parents=True)

    def write_state(self, goal="website"):
        self.state.write_text(json.dumps({"metadata": {
            "os_name": "Aurora <Test>", "agent_name": "Trace & Co", "first_goal": goal,
        }}), encoding="utf-8")
        self.state.chmod(0o600)

    def run_goal(self, action):
        result = subprocess.run([sys.executable, str(RUNNER), action], env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_website_preview_and_preserved_client_edit(self):
        self.write_state()
        port = free_preview_port()
        registry = self.home / "srv/fleetdeck/services.json"
        registry.parent.mkdir(parents=True)
        registry.write_text('{"services": []}\n', encoding="utf-8")
        status_path = self.home / ".wideband/first-goal/status.json"
        status_path.parent.mkdir(parents=True)
        status_path.write_text(json.dumps({"port": port}), encoding="utf-8")
        self.assertEqual(self.run_goal("apply")["status"], "prepared")
        self.assertEqual(status_path.stat().st_mode & 0o777, 0o600)
        public = self.home / "wideband/first-project/public"
        page = public / "index.html"
        self.assertIn("Aurora &lt;Test&gt;", page.read_text(encoding="utf-8"))
        self.assertIn("Trace &amp; Co", page.read_text(encoding="utf-8"))
        self.assertIn('rel="apple-touch-icon"', page.read_text(encoding="utf-8"))
        self.assertTrue((public / "icons/apple-touch-icon.png").is_file())
        self.assertEqual(json.loads((public / "manifest.webmanifest").read_text())["display"], "standalone")
        (public / ".secret").write_text("hidden", encoding="utf-8")
        server = subprocess.Popen([sys.executable, str(SERVER), "--directory", str(public),
                                   "--port", str(port)], stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (server.terminate(), server.wait(timeout=3)))
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=.2).close()
                break
            except (OSError, urllib.error.URLError):
                time.sleep(.05)
        else:
            self.fail("preview server did not start")
        self.assertEqual(self.run_goal("apply")["status"], "ready")
        self.assertEqual(self.run_goal("check")["status"], "ready")
        self.assertEqual(json.loads(registry.read_text())["services"][0]["name"], "Aurora <Test> · First project")
        self.assertTrue(json.loads(registry.read_text())["services"][0]["install"])
        self.write_state()
        updated = json.loads(self.state.read_text())
        updated["metadata"]["os_name"] = "Nova"
        self.state.write_text(json.dumps(updated), encoding="utf-8")
        self.assertEqual(self.run_goal("apply")["os_name"], "Nova")
        self.assertIn("Nova is live", page.read_text(encoding="utf-8"))
        self.assertEqual(json.loads(registry.read_text())["services"][0]["name"], "Nova · First project")
        with self.assertRaises(urllib.error.HTTPError) as hidden:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/.secret", timeout=1)
        self.assertEqual(hidden.exception.code, 404)
        hidden.exception.close()
        page.write_text("client edit", encoding="utf-8")
        self.run_goal("apply")
        self.assertEqual(page.read_text(encoding="utf-8"), "client edit")
        updated["metadata"]["first_goal"] = "research"
        self.state.write_text(json.dumps(updated), encoding="utf-8")
        self.assertEqual(self.run_goal("apply")["goal"], "research")
        self.assertFalse((self.home / "Library/LaunchAgents/ai.wideband.first-project.plist").exists())
        self.assertEqual(json.loads(registry.read_text())["services"], [])
        self.assertEqual(page.read_text(encoding="utf-8"), "client edit")

    def test_research_creates_only_a_brief(self):
        self.write_state("research")
        status = self.run_goal("apply")
        self.assertEqual(status["goal"], "research")
        self.assertEqual(status["status"], "prepared")
        self.assertIsNone(status["service_id"])
        self.assertEqual(self.run_goal("check")["goal"], "research")
        self.assertFalse((self.home / "wideband/first-project/public").exists())

    def test_health_requires_the_actual_page(self):
        public = self.home / "public"
        public.mkdir()
        port = free_preview_port()
        server = subprocess.Popen([sys.executable, str(SERVER), "--directory", str(public),
                                   "--port", str(port)], stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (server.terminate(), server.wait(timeout=3)))
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=.2).close()
                break
            except (OSError, urllib.error.URLError):
                time.sleep(.05)
        else:
            self.fail("preview server did not start")
        self.assertFalse(runner.site_ready(port), "health marker alone is insufficient")
        (public / "index.html").write_text("<!doctype html><title>Ready</title>", encoding="utf-8")
        self.assertTrue(runner.site_ready(port))
        (public / "index.html").unlink()
        self.assertFalse(runner.site_ready(port), "a removed page must clear readiness")

    def test_phone_url_requires_https_response(self):
        port = 4173
        url = "https://agent.example.ts.net:4173"
        serve = {"TCP": {"4173": {"HTTPS": True}}, "Web": {
            "agent.example.ts.net:4173": {"Handlers": {
                "/": {"Proxy": "http://127.0.0.1:4173"}}}}}
        answer = subprocess.CompletedProcess([], 0, json.dumps(serve), "")

        class Page(io.BytesIO):
            status = 200

            def __init__(self, page_url, body, content_type):
                super().__init__(body)
                self.url = page_url
                self.headers = type("Headers", (), {
                    "get_content_type": lambda self: content_type})()

        def serving(path, timeout):
            if path == url:
                return Page(url, b"<!doctype html><title>Project</title>", "text/html")
            if path == url + "/health":
                return Page(path, b'{"service":"wideband-first-project"}', "application/json")
            raise AssertionError(path)

        with mock.patch.object(runner.Path, "is_file", return_value=True), \
             mock.patch.object(runner.os, "access", return_value=True), \
             mock.patch.object(runner.subprocess, "run", return_value=answer) as ts_run, \
             mock.patch.object(runner.time, "sleep"):
            with mock.patch.object(runner.urllib.request, "urlopen",
                                   side_effect=urllib.error.URLError("TLS failed")):
                self.assertIsNone(runner.phone_url(port))
            with mock.patch.object(runner.urllib.request, "urlopen", side_effect=serving) as get:
                self.assertEqual(runner.phone_url(port), url)
                self.assertEqual([call.args[0] for call in get.call_args_list],
                                 [url, url + "/health"])
            with mock.patch.object(runner.urllib.request, "urlopen",
                                   side_effect=lambda path, timeout: Page(
                                       "https://login.example.test", b"<html>Sign in</html>",
                                       "text/html")):
                self.assertIsNone(runner.phone_url(port),
                                  "a redirected login page is not the project")
        self.assertTrue(ts_run.call_args_list)
        self.assertTrue(all(call.kwargs["env"]["TAILSCALE_BE_CLI"] == "1"
                            for call in ts_run.call_args_list))

    def test_phone_url_refuses_public_funnel_route(self):
        port = 4173
        hostport = "agent.example.ts.net:4173"
        serve = {"TCP": {"4173": {"HTTPS": True}}, "Web": {
            hostport: {"Handlers": {"/": {"Proxy": "http://127.0.0.1:4173"}}}},
            "AllowFunnel": {hostport: True}}
        answer = subprocess.CompletedProcess([], 0, json.dumps(serve), "")
        with mock.patch.object(runner.Path, "is_file", return_value=True), \
             mock.patch.object(runner.os, "access", return_value=True), \
             mock.patch.object(runner.subprocess, "run", return_value=answer) as ts_run, \
             mock.patch.object(runner.urllib.request, "urlopen") as get:
            self.assertIsNone(runner.phone_url(port))
        self.assertEqual(len(ts_run.call_args_list), 1,
                         "a public route must not trigger a Serve reconfiguration")
        self.assertEqual(ts_run.call_args.args[0][1:3], ["serve", "status"])
        get.assert_not_called()

    def test_retire_phone_route_uses_cli_mode(self):
        serve = {"Web": {"agent.example.ts.net:4173": {"Handlers": {
            "/": {"Proxy": "http://127.0.0.1:4173"}}}}}
        replies = [subprocess.CompletedProcess([], 0, json.dumps(serve), ""),
                   subprocess.CompletedProcess([], 0, "", "")]
        with mock.patch.object(runner.Path, "is_file", return_value=True), \
             mock.patch.object(runner.os, "access", return_value=True), \
             mock.patch.object(runner.subprocess, "run", side_effect=replies) as ts_run:
            self.assertIsNone(runner.retire_phone_route(4173))
        self.assertEqual(len(ts_run.call_args_list), 2)
        self.assertTrue(all(call.kwargs["env"]["TAILSCALE_BE_CLI"] == "1"
                            for call in ts_run.call_args_list))

    def test_tailscale_timeout_clears_old_phone_url(self):
        self.write_state()
        status_path = self.home / ".wideband/first-goal/status.json"
        status_path.parent.mkdir(parents=True)
        status_path.write_text(json.dumps({
            "goal": "website", "os_name": "Aurora <Test>", "agent_name": "Trace & Co",
            "port": 4173, "status": "ready", "phone_url": "https://old.example.ts.net"}),
            encoding="utf-8")
        icon = self.home / "brand.png"
        icon.write_bytes(b"icon")
        with mock.patch.multiple(
                runner, HOME=self.home, STATE=self.state,
                GOAL_DIR=self.home / ".wideband/first-goal",
                STATUS=status_path, PROJECT=self.home / "wideband/first-project",
                BRAND_ICON=icon), \
             mock.patch.object(runner, "start_server"), \
             mock.patch.object(runner, "site_ready", return_value=True), \
             mock.patch.object(runner, "register_fleetdeck"), \
             mock.patch.object(runner.Path, "is_file", return_value=True), \
             mock.patch.object(runner.os, "access", return_value=True), \
             mock.patch.object(runner.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired(["tailscale"], 8)), \
             mock.patch.dict(os.environ, {"WB_FIRST_GOAL_SKIP_LAUNCHD": "0"}):
            outcome = runner.apply()
        self.assertEqual(outcome["status"], "ready")
        self.assertNotIn("phone_url", outcome)
        self.assertNotIn("phone_url", json.loads(status_path.read_text()))


if __name__ == "__main__":
    unittest.main()
