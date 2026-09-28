#!/usr/bin/env python3
"""Read-only phone-link proof tests; no real Tailscale or network calls."""

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("wb_setup_phone_link", ROOT / "setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)

DNS = "aurora.example-tailnet.ts.net"
PORT = 8790
TOKEN = "a" * 64
SERVE = {
    "TCP": {str(port): {"HTTPS": True} for port in
            (PORT, setup.FLEET_MAP_TLS_PORT, setup.GRAPH_TLS_PORT, setup.CHAT_TLS_PORT)},
    "Web": {f"{DNS}:{port}": {"Handlers": {"/": {"Proxy": f"http://127.0.0.1:{local}"}}}
            for port, local in ((PORT, PORT),
                                (setup.FLEET_MAP_TLS_PORT, setup.FLEET_MAP_LOCAL_PORT),
                                (setup.GRAPH_TLS_PORT, setup.GRAPH_LOCAL_PORT),
                                (setup.CHAT_TLS_PORT, setup.CHAT_LOCAL_PORT))},
}


class PhoneLinkTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="wb-phone-link-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        token_dir = self.home / ".wideband" / "fleetdeck"
        token_dir.mkdir(parents=True, mode=0o700)
        self.token_file = token_dir / "phone-access-token"
        self.token_file.write_text(TOKEN + "\n", encoding="ascii")
        self.token_file.chmod(0o600)
        environment = mock.patch.dict(os.environ, {"FLEETDECK_ACCESS_TOKEN_PATH": str(self.token_file)})
        environment.start()
        self.addCleanup(environment.stop)
        config = self.home / "srv" / "fleetdeck" / "config.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"ports": {"portal": PORT}}), encoding="utf-8")
        tail = self.home / "Applications" / "Tailscale.app" / "Contents" / "MacOS" / "Tailscale"
        tail.parent.mkdir(parents=True)
        tail.write_text("", encoding="utf-8")
        tail.chmod(0o755)
        self.state = {
            "lifecycle": {"deactivated_at": None},
            "action_runs": {"run_phone_install": {"status": "complete"}},
        }
        self.serve = json.loads(json.dumps(SERVE))
        self.dns = DNS
        self.probe_calls = []
        self.surface_calls = []
        self.api_calls = []
        self.https_healthy = True
        self.surface_healthy = True
        self.api_healthy = True

    def run_tailscale(self, command, **kwargs):
        self.assertEqual(kwargs["env"]["TAILSCALE_BE_CLI"], "1")
        args = command[1:]
        if args == ["status", "--json"]:
            payload = {"Self": {"DNSName": self.dns + "."}}
        elif args == ["serve", "status", "--json"]:
            payload = self.serve
        else:
            raise AssertionError(f"unexpected Tailscale call: {args}")
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    def probe(self, scheme, host, port):
        self.probe_calls.append((scheme, host, port))
        return scheme == "http" or self.https_healthy

    def surface_probe(self, host, port, path):
        self.surface_calls.append((host, port, path))
        return self.surface_healthy

    def api_probe(self, host, port, path):
        self.api_calls.append((host, port, path))
        return self.api_healthy

    def inspect(self):
        return setup.phone_portal_link(
            self.home, self.state, runner=self.run_tailscale,
            probe=self.probe, surface_probe=self.surface_probe, api_probe=self.api_probe,
        )

    def test_ready_requires_local_and_https_health(self):
        result = self.inspect()
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["url"], f"https://{DNS}:{PORT}/p/{TOKEN}/board")
        self.assertEqual(self.probe_calls, [("http", "127.0.0.1", PORT), ("https", DNS, PORT)])
        self.assertEqual(self.surface_calls, [
            (DNS, PORT, f"/p/{TOKEN}/board"),
            (DNS, setup.FLEET_MAP_TLS_PORT, f"/p/{TOKEN}/fleet-map"),
            (DNS, setup.GRAPH_TLS_PORT, f"/p/{TOKEN}/graph"),
            (DNS, setup.CHAT_TLS_PORT, f"/p/{TOKEN}/chat"),
        ])
        self.assertIn((DNS, setup.FLEET_MAP_TLS_PORT, f"/p/{TOKEN}/api/fleet-map"), self.api_calls)
        self.assertIn((DNS, setup.GRAPH_TLS_PORT, f"/p/{TOKEN}/api/stats"), self.api_calls)
        self.assertIn((DNS, setup.CHAT_TLS_PORT, f"/p/{TOKEN}/chat"), self.api_calls)

    def test_wrong_access_token_or_old_portal_never_exposes_link(self):
        self.surface_healthy = False
        result = self.inspect()
        self.assertEqual(result["status"], "needs_attention")
        self.assertNotIn("url", result)
        self.assertEqual(self.surface_calls, [(DNS, PORT, f"/p/{TOKEN}/board")])

    def test_incomplete_live_stack_never_exposes_link(self):
        self.serve["Web"].pop(f"{DNS}:{setup.FLEET_MAP_TLS_PORT}")
        self.assertNotIn("url", self.inspect())
        self.serve = json.loads(json.dumps(SERVE))
        self.api_healthy = False
        self.assertNotIn("url", self.inspect())

    def test_missing_or_unsafe_access_token_never_exposes_link(self):
        self.token_file.unlink()
        self.assertNotIn("url", self.inspect())
        self.token_file.write_text(TOKEN, encoding="ascii")
        self.token_file.chmod(0o644)
        self.assertNotIn("url", self.inspect())
        self.token_file.chmod(0o600)
        self.token_file.write_text("A" + TOKEN[1:], encoding="ascii")
        self.assertNotIn("url", self.inspect())
        self.token_file.write_text(TOKEN + "\nextra", encoding="ascii")
        self.assertNotIn("url", self.inspect())
        self.assertEqual(self.probe_calls, [])

    def test_symlinked_access_token_never_exposes_link(self):
        target = self.home / "target-token"
        target.write_text(TOKEN, encoding="ascii")
        target.chmod(0o600)
        self.token_file.unlink()
        self.token_file.symlink_to(target)
        self.assertNotIn("url", self.inspect())
        self.assertEqual(self.probe_calls, [])

    def test_no_install_or_deactivation_never_exposes_link(self):
        self.state["action_runs"].clear()
        self.assertNotIn("url", self.inspect())
        self.assertEqual(self.probe_calls, [])
        self.state["action_runs"]["run_phone_install"] = {"status": "complete"}
        self.state["lifecycle"]["deactivated_at"] = "2026-09-27T00:00:00Z"
        self.assertNotIn("url", self.inspect())
        self.assertEqual(self.probe_calls, [])

    def test_wrong_host_or_proxy_never_exposes_link(self):
        self.dns = "different.example-tailnet.ts.net"
        self.assertNotIn("url", self.inspect())
        self.dns = DNS
        self.serve["Web"][f"{DNS}:{PORT}"]["Handlers"]["/"]["Proxy"] = "http://127.0.0.1:8783"
        self.assertNotIn("url", self.inspect())
        self.assertEqual([call[0] for call in self.probe_calls], ["http", "http"])

    def test_failed_https_and_non_https_mapping_never_expose_link(self):
        self.https_healthy = False
        self.assertNotIn("url", self.inspect())
        self.assertEqual(self.probe_calls[-1], ("https", DNS, PORT))
        self.serve["TCP"][str(PORT)]["HTTPS"] = False
        before = len(self.probe_calls)
        self.assertNotIn("url", self.inspect())
        self.assertEqual(len(self.probe_calls), before + 1)

    def test_public_funnel_never_exposes_private_link(self):
        self.serve["AllowFunnel"] = {f"{DNS}:{PORT}": True}
        result = self.inspect()
        self.assertEqual(result["status"], "needs_attention")
        self.assertNotIn("url", result)
        self.assertEqual(self.probe_calls, [("http", "127.0.0.1", PORT)])

    def test_malformed_status_fails_closed(self):
        self.serve["Web"][f"{DNS}:{PORT}"]["Handlers"] = {"/": {"Proxy": 1}}
        self.assertNotIn("url", self.inspect())
        self.serve["Web"][f"{DNS}:{PORT}"]["Handlers"] = {"/": "not a handler"}
        self.assertNotIn("url", self.inspect())

    def test_saved_project_shortcut_tracks_current_funnel_state(self):
        project_port = 4173
        hostport = f"{DNS}:{project_port}"
        project_url = f"https://{hostport}"
        self.serve = {
            "TCP": {str(project_port): {"HTTPS": True}},
            "Web": {hostport: {"Handlers": {
                "/": {"Proxy": f"http://127.0.0.1:{project_port}/"}}}},
        }
        metadata = {"os_name": "Aurora", "agent_name": "Trace", "first_goal": "website"}
        status = self.home / ".wideband" / "first-goal" / "status.json"
        status.parent.mkdir(parents=True)
        status.write_text(json.dumps({**metadata, "goal": "website", "status": "ready",
                                      "port": project_port, "phone_url": project_url}), encoding="utf-8")
        with mock.patch.object(setup.subprocess, "run", side_effect=self.run_tailscale):
            self.assertEqual(setup.read_first_goal_status(self.home, metadata)["phone_url"], project_url)
            self.serve["AllowFunnel"] = {hostport: True}
            self.assertNotIn("phone_url", setup.read_first_goal_status(self.home, metadata))
            self.serve["AllowFunnel"] = {}
            self.serve["Web"][hostport]["Handlers"]["/"]["Proxy"] = "http://127.0.0.1:9999"
            self.assertNotIn("phone_url", setup.read_first_goal_status(self.home, metadata))


if __name__ == "__main__":
    unittest.main()
