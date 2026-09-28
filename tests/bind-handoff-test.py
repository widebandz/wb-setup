#!/usr/bin/env python3
"""The owner-chat bind runs under Wideband Agent's LaunchServices identity."""

import importlib.util
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("wb_setup_bind_test", ROOT / "setup.py")
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


class BindHandoffTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="wb-bind-test-")
        self.addCleanup(self.temp.cleanup)
        self.store = setup.StateStore(Path(self.temp.name) / "setup")
        self.runner = setup.JobRunner(self.store)

    def invoke(self, output, errors="", returncode=0):
        captured = {}

        def launch(command, **kwargs):
            self.assertEqual(command[:3], ["/usr/bin/open", "-W", "-n"])
            self.assertTrue(command[3].endswith("/Applications/Wideband Agent.app"))
            self.assertEqual(command[4], "--stdout")
            self.assertEqual(command[6], "--stderr")
            self.assertEqual(command[8:11], ["--args", "run-background-task", "/opt/homebrew/bin/python3"])
            self.assertEqual(command[-2:], ["bind", "--confirm-separate-account"])
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            self.assertEqual(kwargs["timeout"], 180)
            stdout_path, stderr_path = Path(command[5]), Path(command[7])
            for path in (stdout_path, stderr_path):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            stdout_path.write_text(output, encoding="utf-8")
            stderr_path.write_text(errors, encoding="utf-8")
            captured["paths"] = (stdout_path, stderr_path)
            return subprocess.CompletedProcess(command, returncode)

        with mock.patch.object(setup.subprocess, "run", side_effect=launch):
            result = self.runner._bind_via_agent_app({"PATH": "/usr/bin"})
        self.assertTrue(all(not path.exists() for path in captured["paths"]))
        return result

    def test_exact_runtime_success_from_private_app_output(self):
        for marker in setup.BIND_SUCCESS_OUTPUT:
            self.assertTrue(self.invoke(marker + "\n"))

    def test_open_exit_zero_without_app_success_fails_closed(self):
        self.assertFalse(self.invoke(""))
        self.assertFalse(self.invoke("some other success\n"))
        self.assertFalse(self.invoke(next(iter(setup.BIND_SUCCESS_OUTPUT)) + "\n", "Messages access denied\n"))
        self.assertFalse(self.invoke(next(iter(setup.BIND_SUCCESS_OUTPUT)) + "\n", returncode=1))

    def test_failed_handoff_does_not_load_services_or_store_raw_output(self):
        job_id = "bind-test"
        self.runner.jobs[job_id] = {
            "id": job_id, "action": "run_imessage_bind", "status": "running",
            "started_at": setup.now(), "finished_at": None, "exit_code": None, "output": "",
        }
        with mock.patch.object(self.runner, "_bind_via_agent_app", return_value=False), \
             mock.patch.object(setup.subprocess, "Popen") as popen:
            self.runner._run(job_id)
        popen.assert_not_called()
        job = self.runner.get(job_id)
        self.assertEqual(job["status"], "needs_attention")
        self.assertNotIn("Messages access denied", job["output"])
        self.assertNotIn("Loading the bound", job["output"])


if __name__ == "__main__":
    unittest.main()
