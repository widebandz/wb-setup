#!/usr/bin/env python3
"""Provider choice remains private and cannot activate an unproved text runtime."""

import http.client
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("wb_setup_provider_test", ROOT / "setup.py")
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


class ProviderChoiceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="wb-provider-test-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.store = setup.StateStore(self.home / ".wideband" / "setup")
        self.app = setup.SetupApp(self.store)
        setup.Handler.app = self.app
        self.server = setup.LoopbackHTTPServer(("127.0.0.1", 0), setup.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 2)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.real_guard = setup.guard_bound_provider_change
        self.guard = mock.patch.object(setup, "guard_bound_provider_change")
        self.guard_mock = self.guard.start()
        self.addCleanup(self.guard.stop)

    def post(self, path, payload):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request("POST", path, body=json.dumps(payload), headers={
                "Content-Type": "application/json", "X-Wideband-Token": self.app.token,
            })
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def choices(self, provider):
        return {"os_name": "Aurora", "agent_name": "Trace",
                "first_goal": "website", "agent_provider": provider}

    def test_legacy_state_defaults_to_claude_and_preview_never_launches(self):
        old = self.store.read()
        self.assertEqual(old["metadata"]["agent_provider"], "")
        status, result = self.post("/api/actions/run_imessage_init", {})
        self.assertEqual(status, 400, result)
        self.assertIn("choose", result["error"])
        old["metadata"].pop("agent_provider")
        old["metadata"].update({"os_name": "Aurora", "agent_name": "Trace", "first_goal": "website"})
        old["completed"]["identify.name-your-system"] = {"source": "onboarding"}
        self.store._write_unlocked(old)
        self.assertEqual(self.store.read()["metadata"]["agent_provider"], "claude")

        for provider in ("codex", "gemini", "grok"):
            status, result = self.post("/api/onboarding", self.choices(provider))
            self.assertEqual(status, 200, result)
            self.assertEqual(result["metadata"]["agent_provider"], provider)
            for action in ("run_imessage_init", "run_imessage_bind"):
                status, result = self.post(f"/api/actions/{action}", {})
                self.assertEqual(status, 409, result)
                self.assertIn("pending runtime verification", result["error"])
            self.assertNotIn("run_imessage_init", self.store.read()["action_runs"])
            self.assertNotIn("run_imessage_bind", self.store.read()["action_runs"])
            status, result = self.post("/api/actions/open_claude_auth", {})
            self.assertEqual(status, 409, result)
            status, result = self.post("/api/steps/identify.authenticate-agent", {"complete": True})
            self.assertEqual(status, 409, result)

    def test_provider_change_clears_previous_auth_confirmation(self):
        status, result = self.post("/api/onboarding", self.choices("claude"))
        self.assertEqual(status, 200, result)
        with mock.patch.object(self.app, "require_claude_authentication"):
            status, result = self.post("/api/steps/identify.authenticate-agent", {"complete": True})
        self.assertEqual(status, 200, result)
        self.store.update(lambda state: state["completed"].update({
            "prove.messaging": {"source": "human"},
        }))
        status, result = self.post("/api/onboarding", self.choices("codex"))
        self.assertEqual(status, 200, result)
        self.assertNotIn("identify.authenticate-agent", self.store.read()["completed"])
        self.assertNotIn("prove.messaging", self.store.read()["completed"])

    def test_claude_confirmation_requires_live_cli_login(self):
        status, result = self.post("/api/onboarding", self.choices("claude"))
        self.assertEqual(status, 200, result)
        auth_path = "/api/steps/identify.authenticate-agent"
        secret = "private-account@example.invalid"
        cases = (
            (0, json.dumps({"loggedIn": False, "email": secret})),
            (0, json.dumps({"loggedIn": "true", "email": secret})),
            (1, json.dumps({"loggedIn": True, "email": secret})),
            (0, "not JSON " + secret),
        )
        with mock.patch.object(self.app, "_claude_executable", return_value="/mock/claude"), \
                mock.patch.object(setup.subprocess, "run") as run:
            for exit_code, output in cases:
                with self.subTest(exit_code=exit_code, output=output[:20]):
                    run.return_value = mock.Mock(returncode=exit_code, stdout=output)
                    status, result = self.post(auth_path, {"complete": True})
                    self.assertEqual(status, 409, result)
                    self.assertIn("not signed in", result["error"])
                    self.assertNotIn(secret, json.dumps(result))
                    self.assertNotIn("identify.authenticate-agent", self.store.read()["completed"])

            run.return_value = mock.Mock(returncode=0, stdout=json.dumps({
                "loggedIn": True, "email": secret,
            }))
            status, result = self.post(auth_path, {"complete": True})
            self.assertEqual(status, 200, result)
            self.assertEqual(result["completed"]["identify.authenticate-agent"]["source"], "human")
            self.assertNotIn(secret, json.dumps(result))
            args, kwargs = run.call_args
            self.assertEqual(args[0], ["/mock/claude", "auth", "status", "--json"])
            self.assertEqual(kwargs["stdin"], setup.subprocess.DEVNULL)
            self.assertEqual(kwargs["stderr"], setup.subprocess.DEVNULL)
            self.assertEqual(kwargs["timeout"], 10)

    def test_claude_auth_check_handles_missing_cli_and_timeout_without_leaking_output(self):
        status, result = self.post("/api/onboarding", self.choices("claude"))
        self.assertEqual(status, 200, result)
        auth_path = "/api/steps/identify.authenticate-agent"
        with mock.patch.object(self.app, "_claude_executable", return_value=None):
            status, result = self.post(auth_path, {"complete": True})
            self.assertEqual(status, 409, result)
            self.assertIn("still installing", result["error"])
        with mock.patch.object(self.app, "_claude_executable", return_value="/mock/claude"), \
                mock.patch.object(setup.subprocess, "run", side_effect=setup.subprocess.TimeoutExpired(
                    ["/mock/claude", "auth", "status", "--json"], 10,
                    output=b"private-token"
                )):
            status, result = self.post(auth_path, {"complete": True})
            self.assertEqual(status, 409, result)
            self.assertNotIn("private-token", json.dumps(result))
        self.assertNotIn("identify.authenticate-agent", self.store.read()["completed"])

    def test_claude_cli_uses_fixed_path_when_gui_path_lacks_it(self):
        cli = self.home / ".local" / "bin" / "claude"
        cli.parent.mkdir(parents=True)
        cli.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        cli.chmod(0o700)
        with mock.patch.object(setup.Path, "home", return_value=self.home), \
                mock.patch.object(setup.shutil, "which", return_value=None):
            self.assertEqual(self.app._claude_executable(), str(cli.resolve()))

    def test_sign_in_helper_uses_auth_login_without_opening_claude_repl(self):
        with mock.patch.object(setup.platform, "system", return_value="Darwin"), \
                mock.patch.object(setup, "resolved_tool_path", return_value=Path(sys.executable)), \
                mock.patch.object(setup.subprocess, "run") as launch:
            self.app.open_claude_auth()
        helper = self.store.directory / "claude-sign-in.command"
        content = helper.read_text(encoding="utf-8")
        self.assertIn("packaging/claude-sign-in.sh", content)
        script = (ROOT / "packaging" / "claude-sign-in.sh").read_text(encoding="utf-8")
        self.assertIn('"$CLAUDE" auth login', script)
        self.assertIn('if ! /usr/bin/curl --fail', script)
        self.assertIn('/bin/bash -n "$installer"', script)
        self.assertNotIn("| bash", script)
        launch.assert_called_once_with(["open", "-a", "Terminal", str(helper)], check=True, timeout=10)

    def test_sign_in_helper_uses_existing_verified_home_cli(self):
        cli = self.home / ".local" / "bin" / "claude"
        cli.parent.mkdir(parents=True)
        args_path = self.home / "claude-args.txt"
        cli.write_text('#!/bin/sh\nprintf "%s\\n" "$*" > "$WB_TEST_CLAUDE_ARGS"\n', encoding="utf-8")
        cli.chmod(0o700)
        result = subprocess.run(
            ["/bin/bash", str(ROOT / "packaging" / "claude-sign-in.sh"), sys.executable],
            env={**os.environ, "HOME": str(self.home), "WB_TEST_CLAUDE_ARGS": str(args_path)},
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(args_path.read_text(encoding="utf-8").strip(), "auth login")

    def test_provider_change_during_auth_check_cannot_confirm_claude(self):
        status, result = self.post("/api/onboarding", self.choices("claude"))
        self.assertEqual(status, 200, result)

        def switch_provider():
            self.store.update(lambda data: data["metadata"].update({"agent_provider": "codex"}))

        with mock.patch.object(self.app, "require_claude_authentication", side_effect=switch_provider):
            status, result = self.post("/api/steps/identify.authenticate-agent", {"complete": True})
        self.assertEqual(status, 409, result)
        self.assertNotIn("identify.authenticate-agent", self.store.read()["completed"])

    def test_invalid_choice_and_bound_provider_change_are_rejected(self):
        for bad in (None, "", "other", ["claude"]):
            choices = self.choices("claude")
            choices["agent_provider"] = bad
            status, _ = self.post("/api/onboarding", choices)
            self.assertEqual(status, 400)

        runtime_path = self.home / ".wideband" / "imessage" / "config.json"
        runtime_path.parent.mkdir(parents=True)
        runtime_path.write_text(json.dumps({
            "agent_command": "claude", "binding": {"chat_id": 7},
        }), encoding="utf-8")
        self.guard_mock.side_effect = lambda provider: self.real_guard(provider, self.home)
        with self.assertRaisesRegex(RuntimeError, "already bound"):
            self.real_guard("codex", self.home)
        status, result = self.post("/api/onboarding", self.choices("codex"))
        self.assertEqual(status, 409, result)
        self.assertIn("already bound", result["error"])
        status, result = self.post("/api/onboarding", self.choices("claude"))
        self.assertEqual(status, 200, result)


if __name__ == "__main__":
    unittest.main()
