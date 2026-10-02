#!/usr/bin/env python3
"""A fresh local Fleetdeck stack must not require or configure Tailscale."""

import importlib.util
import json
import os
import plistlib
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / "packaging" / "phone-stack.py"
spec = importlib.util.spec_from_file_location("wideband_phone_stack", SOURCE)
stack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stack)


class LocalPhoneStackTest(unittest.TestCase):
    def test_chat_log_is_private_and_generated_ttyd_secret_rotates(self):
        with tempfile.TemporaryDirectory(prefix="wb-local-chat-secret-") as directory:
            root = Path(directory)
            fleetdeck = root / "fleetdeck"
            logs = root / "setup"
            fleetdeck.mkdir()
            logs.mkdir()
            credential = fleetdeck / "auth"
            credential.write_text("fleet:" + "a" * 24)
            credential.chmod(0o600)
            log = logs / "com.wideband.test.fleetdeck-chat.log"
            log.write_text("old ttyd credential might be here")
            log.chmod(0o644)
            with mock.patch.multiple(stack, FD=fleetdeck, LOG_DIR=logs):
                stack.rotate_internal_ttyd_credential("com.wideband.test.fleetdeck-chat")
                self.assertNotEqual(credential.read_text(), "fleet:" + "a" * 24)
                self.assertEqual(log.read_text(), "")
                self.assertEqual(stat.S_IMODE(log.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(logs.stat().st_mode), 0o700)
                credential.write_text("custom-secret")
                with self.assertRaisesRegex(ValueError, "customized"):
                    stack.rotate_internal_ttyd_credential("com.wideband.test.fleetdeck-chat")

    def test_runtime_tools_must_share_one_verified_bin(self):
        with tempfile.TemporaryDirectory(prefix="wb-local-tools-") as directory:
            base = Path(directory)
            (base / "other").mkdir()
            for tool in ("python3", "tmux", "node", "npm", "ttyd"):
                (base / tool).write_text("tool")
            (base / "other" / "npm").write_text("tool")
            def resolve(_resolver, tool, *, check=False):
                location = base / tool if tool != "npm" else base / "other" / tool
                return subprocess.CompletedProcess([], 0, str(location) + "\n", "")
            with mock.patch.object(stack, "call", side_effect=resolve):
                with self.assertRaisesRegex(ValueError, "different installations"):
                    stack.toolchain_bin()

    def test_custom_port_is_rejected_before_service_changes(self):
        with tempfile.TemporaryDirectory(prefix="wb-local-stack-") as directory:
            fleetdeck = Path(directory)
            (fleetdeck / "config.json").write_text(json.dumps({
                "label_prefix": "com.wideband.test", "ports": {"portal": 8890}}))
            with mock.patch.object(stack, "FD", fleetdeck), \
                 mock.patch.object(stack, "ensure_job") as job:
                with self.assertRaisesRegex(ValueError, "ports differ"):
                    stack.run()
                job.assert_not_called()

    def test_zero_session_map_and_local_services_need_no_tailscale(self):
        with tempfile.TemporaryDirectory(prefix="wb-local-stack-") as directory:
            root = Path(directory)
            fleetdeck = root / "fleetdeck"
            launchagents = root / "LaunchAgents"
            fleetdeck.mkdir()
            launchagents.mkdir()
            (fleetdeck / "config.json").write_text(
                json.dumps({"label_prefix": "com.wideband.test", "machine": ""}))
            (fleetdeck / ".wideband-fleetdeck-bundle.json").write_text("{}")
            (fleetdeck / "chat_server.py").write_text("FLEETDECK_CUSTOMER_TERMINALS")
            portal_label = "com.wideband.test.fleetdeck-portal"
            (launchagents / f"{portal_label}.plist").write_bytes(plistlib.dumps({
                "Label": portal_label,
                "ProgramArguments": [sys.executable, str(fleetdeck / "portal_server.py")],
                "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/bin:/bin"},
            }))
            jobs = {}
            registered = []
            calls = []

            def ensure_job(label, content):
                jobs[label] = plistlib.loads(content)

            def call(*argv, **_kwargs):
                calls.append(argv)
                return subprocess.CompletedProcess(argv, 0, "", "")

            def get_json(url, *, host=None):
                if url.endswith("/api/fleet-map"):
                    self.assertEqual(host, "wideband.localhost:18790")
                    return {"schema_version": "agent-fleet.snapshot.v1",
                            "nodes": [{"id": "host:local", "type": "host", "observed": True}],
                            "summary": {"live_sessions": 0}}
                if url.endswith("/api/stats"):
                    return {"nodes": 1, "run": {"at": "now"}}
                if url.endswith("/api/graph?lens=surface"):
                    return {"nodes": [{"id": "local"}], "edges": [{"from": "local"}]}
                raise AssertionError(url)

            def wait_ready(label, predicate):
                if label in ("Live Terminal Network", "Knowledge Graph",
                             "refreshed Knowledge Graph"):
                    self.assertTrue(predicate(), label)

            with mock.patch.multiple(stack, FD=fleetdeck, LA=launchagents,
                                     LOG_DIR=root / "setup", TS_APP=root / "missing-tailscale"), \
                 mock.patch.dict(os.environ, os.environ.copy()), \
                 mock.patch.object(stack, "toolchain_bin", return_value=root / "tools"), \
                 mock.patch.object(stack, "prepare_graph", return_value="/usr/bin/node"), \
                 mock.patch.object(stack, "rotate_internal_ttyd_credential"), \
                 mock.patch.object(stack, "read_token", return_value="a" * 64), \
                 mock.patch.object(stack, "ensure_job", side_effect=ensure_job), \
                 mock.patch.object(stack, "call", side_effect=call), \
                 mock.patch.object(stack, "get_json", side_effect=get_json), \
                 mock.patch.object(stack, "wait_ready", side_effect=wait_ready), \
                 mock.patch.object(stack, "refresh_graph_index"), \
                 mock.patch.object(stack, "register_service", side_effect=registered.append), \
                 mock.patch.object(stack, "ensure_serve") as serve:
                stack.run()

            serve.assert_not_called()
            self.assertIn(("launchctl", "kickstart", "-k",
                           f"gui/{os.getuid()}/com.wideband.test.fleetdeck-map"), calls)
            self.assertIn(("launchctl", "kickstart", "-k",
                           f"gui/{os.getuid()}/com.wideband.test.fleetdeck-chat"), calls)
            self.assertEqual(jobs[portal_label]["EnvironmentVariables"]["FLEETDECK_HOST"],
                             "wideband.localhost")
            self.assertEqual(jobs[portal_label]["EnvironmentVariables"]["PATH"],
                             str(root / "tools") + ":/usr/bin:/bin:/usr/sbin:/sbin")
            self.assertEqual(jobs[portal_label]["EnvironmentVariables"]["FLEETDECK_MAP_ORIGIN"],
                             "http://wideband.localhost:18790")
            self.assertEqual(jobs["com.wideband.test.fleetdeck-map"]
                             ["EnvironmentVariables"]["FLEETDECK_BOARD_ORIGIN"],
                             "http://wideband.localhost:8790")
            self.assertEqual(jobs["com.wideband.test.fleetdeck-chat"]
                             ["EnvironmentVariables"]["FLEETDECK_LOCAL_ONLY"], "1")
            self.assertEqual({item["id"] for item in registered}, {"chat", "graph"})


if __name__ == "__main__":
    unittest.main()
