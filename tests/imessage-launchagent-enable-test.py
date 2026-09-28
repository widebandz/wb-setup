#!/usr/bin/env python3
"""Exercise recovery from launchd's persistent disabled state in isolation."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JOBS = ("keep", "route", "watch", "outbox")


class DisabledLaunchAgentsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="wb-imessage-disabled-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.launch_agents = self.home / "Library" / "LaunchAgents"
        self.launch_agents.mkdir(parents=True)
        (self.home / ".sop-vars").write_text(
            "export ORG=example\nexport BRAND=Wideband\n"
            "export OPERATOR_PHONE=+15551234567\n", encoding="utf-8",
        )
        agent = self.home / "Applications" / "Wideband Agent.app" / "Contents" / "MacOS" / "Wideband Agent"
        agent.parent.mkdir(parents=True)
        agent.write_text(
            "#!/bin/sh\n"
            "if [ \"${WB_TARGET_VERIFIED:-0}\" = 1 ]; then\n"
            "  echo '{\"target_verified\":true}'\n"
            "else\n"
            "  echo '{\"target_verified\":false}'\n"
            "fi\n", encoding="utf-8",
        )
        agent.chmod(0o755)
        self.bin = self.home / "fakebin"
        self.bin.mkdir()
        self.disabled = self.home / "disabled"
        self.disabled.mkdir()
        self.loaded = self.home / "loaded"
        self.loaded.mkdir()
        self.log = self.home / "launchctl.log"
        launchctl = self.bin / "launchctl"
        launchctl.write_text(
            "#!/bin/sh\n"
            "printf '%s %s %s\\n' \"$1\" \"$2\" \"${3:-}\" >> \"$WB_TEST_LAUNCH_LOG\"\n"
            "label=${2##*/}\n"
            "case \"$1\" in\n"
            "  print-disabled)\n"
            "    echo 'disabled services = {'\n"
            "    for file in \"$WB_TEST_DISABLED\"/*; do\n"
            "      [ -f \"$file\" ] || continue\n"
            "      printf '\\t\"%s\" => disabled\\n' \"${file##*/}\"\n"
            "    done\n"
            "    echo '}' ;;\n"
            "  print) test -f \"$WB_TEST_LOADED/$label\" ;;\n"
            "  bootout) rm -f \"$WB_TEST_LOADED/$label\" ;;\n"
            "  enable)\n"
            "    if [ \"$label\" = \"${WB_FAIL_ENABLE_LABEL:-}\" ]; then\n"
            "      echo 'simulated enable failure' >&2; exit 1\n"
            "    fi\n"
            "    rm -f \"$WB_TEST_DISABLED/$label\" ;;\n"
            "  bootstrap)\n"
            "    label=${3##*/}; label=${label%.plist}\n"
            "    if [ -f \"$WB_TEST_DISABLED/$label\" ]; then\n"
            "      echo 'Bootstrap failed: 5' >&2; exit 5\n"
            "    fi\n"
            "    touch \"$WB_TEST_LOADED/$label\" ;;\n"
            "  *) exit 99 ;;\n"
            "esac\n", encoding="utf-8",
        )
        launchctl.chmod(0o755)
        for name, body in (("sw_vers", "echo 15.0\n"), ("tmux", "exit 0\n"),
                           ("imsg", "exit 0\n")):
            script = self.bin / name
            script.write_text("#!/bin/sh\n" + body, encoding="utf-8")
            script.chmod(0o755)
        self.env = dict(
            os.environ, HOME=str(self.home),
            PATH=str(self.bin) + ":" + os.environ.get("PATH", ""),
            WB_TEST_LAUNCH_LOG=str(self.log),
            WB_TEST_DISABLED=str(self.disabled),
            WB_TEST_LOADED=str(self.loaded),
        )

    def run_install(self, **env_overrides):
        return subprocess.run(
            ["bash", str(ROOT / "install.sh"), "--imessage-only", "--no-verify"],
            env={**self.env, **env_overrides}, capture_output=True,
            text=True, timeout=20, check=False,
        )

    def save_binding(self):
        cfg = self.home / ".wideband" / "imessage" / "config.json"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps({"schema_version": 1, "binding": {
            "chat_id": 7, "chat_guid": "iMessage;-;+15551234567",
            "account_login": "head@example.test",
        }}), encoding="utf-8")

    def test_only_verified_bound_jobs_are_reenabled_before_bootstrap(self):
        for job in JOBS:
            (self.disabled / f"com.example.imessage-{job}").touch()
        (self.disabled / "com.other.healthcheck").touch()

        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(list(self.launch_agents.glob("com.example.imessage-*.plist")))
        self.assertFalse(list(self.loaded.iterdir()))
        self.assertNotIn("enable ", self.log.read_text())

        self.save_binding()
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(list(self.launch_agents.glob("com.example.imessage-*.plist")))
        self.assertNotIn("enable ", self.log.read_text())

        result = self.run_install(WB_TARGET_VERIFIED="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = self.log.read_text().splitlines()
        for job in JOBS:
            label = f"com.example.imessage-{job}"
            self.assertFalse((self.disabled / label).exists())
            self.assertTrue((self.loaded / label).is_file())
            self.assertTrue((self.launch_agents / f"{label}.plist").is_file())
            enable_line = f"enable gui/{os.getuid()}/{label} "
            bootstrap_line = f"bootstrap gui/{os.getuid()} {self.launch_agents / (label + '.plist')}"
            self.assertIn(enable_line, lines)
            self.assertIn(bootstrap_line, lines)
            self.assertLess(lines.index(enable_line), lines.index(bootstrap_line))
        self.assertTrue((self.disabled / "com.other.healthcheck").exists())
        self.assertFalse(any("com.other.healthcheck" in line for line in lines))

        previous_enables = sum(line.startswith("enable ") for line in lines)
        result = self.run_install(WB_TARGET_VERIFIED="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(sum(line.startswith("enable ") for line in self.log.read_text().splitlines()),
                         previous_enables)

    def test_enable_failure_keeps_affected_job_unloaded(self):
        self.save_binding()
        label = "com.example.imessage-route"
        (self.disabled / label).touch()
        result = self.run_install(WB_TARGET_VERIFIED="1", WB_FAIL_ENABLE_LABEL=label)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("could not be re-enabled", result.stdout)
        self.assertFalse((self.loaded / label).exists())
        self.assertTrue((self.disabled / label).exists())


if __name__ == "__main__":
    unittest.main()
