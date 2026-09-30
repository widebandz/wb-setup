#!/usr/bin/env python3
"""Account-free local setup and truthful preflight gates."""

import importlib.util
import http.client
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("wb_setup_preflight", ROOT / "setup.py")
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


class PreflightGatesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="wb-preflight-test-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.store = setup.StateStore(self.home / ".wideband" / "setup")
        self.runner = setup.JobRunner(self.store)
        self.store.update(lambda state: state["metadata"].update({
            "os_name": "Aurora",
            "agent_name": "Trace",
            "agent_provider": "claude",
            "first_goal": "website",
        }))

    def test_foreign_homebrew_is_inventory_without_repair_command(self):
        prefix = self.home / "homebrew"
        prefix.mkdir()
        with mock.patch.object(setup.os, "getuid", return_value=prefix.stat().st_uid + 1):
            self.assertEqual(setup.default_homebrew_class(prefix), "foreign_owner")
        with mock.patch.object(setup, "bootstrap_status", return_value="needs_independent_toolchain"), \
                mock.patch.object(setup, "default_homebrew_class", return_value="foreign_owner"):
            report = setup.core_preflight(self.store.directory)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["reason_code"], "needs_independent_toolchain")
        self.assertEqual(report["default_homebrew"], "foreign_owner")
        self.assertNotIn("chown", json.dumps(report))
        self.assertNotIn(str(prefix), json.dumps(report))

    def test_mutating_actions_stop_before_account_or_message_work_when_core_blocked(self):
        self.store.update(lambda state: state["completed"].update({
            "prepare.create-accounts": {"source": "human"},
            "connect.messages": {"source": "human"},
        }))
        with mock.patch.object(setup, "bootstrap_status", return_value="needs_independent_toolchain"):
            for action in ("run_install", "run_imessage_install", "run_imessage_init", "run_imessage_bind"):
                with self.subTest(action=action), self.assertRaisesRegex(RuntimeError, "needs_independent_toolchain"):
                    self.runner.start(action)
        self.assertEqual(self.runner.jobs, {})
        self.assertEqual(self.store.read()["action_runs"], {})

    def test_client_package_blocks_legacy_full_install_before_job_mutation(self):
        marker = self.store.directory / "client-package"
        marker.write_text("test-build\n", encoding="ascii")
        marker.chmod(0o600)
        with mock.patch.object(setup, "require_core_tools", side_effect=AssertionError("should not resolve tools")):
            with self.assertRaisesRegex(RuntimeError, "legacy_full_install_disabled"):
                self.runner.start("run_install")
            started_as_client = setup.JobRunner(self.store)
        marker.unlink()
        with mock.patch.object(setup, "require_core_tools", side_effect=AssertionError("should not resolve tools")):
            with self.assertRaisesRegex(RuntimeError, "legacy_full_install_disabled"):
                started_as_client.start("run_install")
        with mock.patch.dict(os.environ, {"WB_SETUP_CLIENT_MODE": "1"}), \
                mock.patch.object(setup, "require_core_tools", side_effect=AssertionError("should not resolve tools")):
            with self.assertRaisesRegex(RuntimeError, "legacy_full_install_disabled"):
                self.runner.start("run_install")
        self.assertEqual(self.runner.jobs, {})
        self.assertEqual(self.store.read()["action_runs"], {})

    def test_private_api_returns_redacted_preflight_and_blocks_bind(self):
        app = setup.SetupApp(self.store)
        setup.Handler.app = app
        server = setup.LoopbackHTTPServer(("127.0.0.1", 0), setup.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def request(method, path, authorized=True):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            try:
                headers = {"X-Wideband-Token": app.token} if authorized else {}
                connection.request(method, path, body=b"{}" if method == "POST" else None, headers=headers)
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally:
                connection.close()

        with mock.patch.object(setup, "bootstrap_status", return_value="needs_independent_toolchain"), \
                mock.patch.object(setup, "default_homebrew_class", return_value="foreign_owner"):
            status, _ = request("GET", "/api/preflight", False)
            self.assertEqual(status, 401)
            status, report = request("GET", "/api/preflight")
            self.assertEqual(status, 200)
            self.assertEqual(report["reason_code"], "needs_independent_toolchain")
            self.assertNotIn(str(self.home), json.dumps(report))
            status, blocked = request("POST", "/api/actions/run_imessage_bind")
            self.assertEqual(status, 409)
            self.assertIn("needs_independent_toolchain", blocked["error"])
            self.assertNotIn(str(self.home), json.dumps(blocked))
        self.assertNotIn("run_imessage_bind", self.store.read()["action_runs"])

    def test_first_job_and_local_board_can_start_without_apple_account_or_phone_reply(self):
        with mock.patch.object(setup, "require_core_tools"), \
                mock.patch.object(setup, "resolved_tool_path", return_value=Path("/usr/bin/python3")), \
                mock.patch.object(self.runner, "_run"):
            first = self.runner.start("run_first_goal_apply")
            self.assertEqual(first["action"], "run_first_goal_apply")
            self.runner.jobs[first["id"]]["status"] = "complete"
            self.store.update(lambda state: state["action_runs"]["run_first_goal_apply"].update({"status": "complete"}))
            phone = self.runner.start("run_phone_install")
            self.assertEqual(phone["action"], "run_phone_install")
        self.assertNotIn("prepare.create-accounts", self.store.read()["completed"])
        self.assertNotIn("prove.messaging", self.store.read()["completed"])

    def test_local_preview_requires_owner_capability_and_actual_page(self):
        token = "a" * 64
        token_file = self.home / "phone-access-token"
        token_file.write_text(token, encoding="ascii")
        token_file.chmod(0o600)
        config = self.home / "srv" / "fleetdeck" / "config.json"
        config.parent.mkdir(parents=True)
        config.write_text('{"ports":{"portal":8790}}', encoding="utf-8")
        state = self.store.read()
        state["action_runs"]["run_phone_install"] = {"status": "complete"}
        with mock.patch.dict(os.environ, {"FLEETDECK_ACCESS_TOKEN_PATH": str(token_file)}):
            result = setup.local_board_preview(
                self.home, state,
                health_probe=lambda port: port == 8790,
                page_probe=lambda port, value: port == 8790 and value == token,
            )
            self.assertEqual(result["status"], "local_ready")
            self.assertEqual(result["local_url"], f"http://wideband.localhost:8790/p/{token}/phone")
            self.assertIn("Mac-only", result["detail"])
            blocked = setup.local_board_preview(
                self.home, state, health_probe=lambda *_: True, page_probe=lambda *_: False,
            )
            self.assertEqual(blocked["status"], "waiting")
            self.assertNotIn("local_url", blocked)
            token_file.chmod(0o644)
            unsafe = setup.local_board_preview(
                self.home, state, health_probe=lambda *_: True, page_probe=lambda *_: True,
            )
            self.assertNotIn("local_url", unsafe)

    def test_support_summary_contains_codes_without_payloads(self):
        self.store.update(lambda state: state.update({
            "last_full_verification": {
                "generated_at": "2026-09-30T12:00:00+00:00",
                "checks": [
                    {"id": "P0-FDA", "status": "fail", "message": "Denied for owner@example.test +15551234567"},
                    {"id": "P6-IMSG", "status": "fail", "message": "No imsg"},
                ],
            },
            "last_verification": {
                "generated_at": "2026-09-30T12:01:00+00:00",
                "summary": {"passed": 0, "failed": 1, "skipped": 0},
                "checks": [{"id": "P6-IMSG", "status": "fail", "message": "No imsg"}],
            },
        }))
        with mock.patch.object(setup, "bootstrap_status", return_value="needs_independent_toolchain"), \
                mock.patch.object(setup, "default_homebrew_class", return_value="foreign_owner"):
            summary = setup.support_summary(self.store)
        self.assertEqual(summary["preflight"]["reason_code"], "needs_independent_toolchain")
        self.assertEqual([item["id"] for item in summary["last_full_permission_checks"]["checks"]], ["P0-FDA"])
        self.assertEqual(summary["last_full_permission_checks"]["evidence_label"], "last_known")
        self.assertNotIn("owner@example.test", json.dumps(summary))
        self.assertNotIn("+15551234567", json.dumps(summary))
        self.assertNotIn("phone-access-token", json.dumps(summary))
        self.assertNotIn(str(self.home), json.dumps(summary))


if __name__ == "__main__":
    unittest.main()
