#!/usr/bin/env python3
"""A client can prepare local setup before storing a private iMessage owner number."""

import importlib.util
import json
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("wb_setup_deferred_phone", ROOT / "setup.py")
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)
PHONE = "+15551234567"


class DeferredOwnerPhoneTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="wb-deferred-phone-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.identity = self.home / ".sop-vars"
        self.identity.write_text("export ORG='wideband'\nexport OPERATOR_PHONE=''\n", encoding="utf-8")
        self.identity.chmod(0o600)
        self.backups = self.home / ".wideband" / "setup" / "backups"

    def test_empty_phone_is_deferred_then_saved_privately(self):
        self.assertFalse(setup.identity_phone_is_set(self.home))
        setup.save_identity_phone(self.home, self.backups, PHONE)
        self.assertTrue(setup.identity_phone_is_set(self.home))
        self.assertEqual(setup.read_identity_phone(self.home), PHONE)
        self.assertIn("export ORG='wideband'", self.identity.read_text())
        self.assertEqual(stat.S_IMODE(self.identity.stat().st_mode), 0o600)
        backup = list(self.backups.glob("sop-vars.before-owner-phone.*"))
        self.assertEqual(len(backup), 1)
        self.assertEqual(stat.S_IMODE(backup[0].stat().st_mode), 0o600)
        self.assertNotIn(PHONE, backup[0].read_text())
        setup.save_identity_phone(self.home, self.backups, PHONE)
        self.assertEqual(len(list(self.backups.iterdir())), 1)

    def test_existing_number_or_runtime_identity_is_preserved(self):
        setup.save_identity_phone(self.home, self.backups, PHONE)
        with self.assertRaisesRegex(RuntimeError, "preserved"):
            setup.save_identity_phone(self.home, self.backups, PHONE[:-1] + "8")
        self.assertEqual(setup.read_identity_phone(self.home), PHONE)
        self.identity.write_text("export OPERATOR_PHONE=''\n", encoding="utf-8")
        config = self.home / ".wideband" / "imessage" / "config.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"owner_phone": PHONE}), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "preserved"):
            setup.save_identity_phone(self.home, self.backups, PHONE)

    def test_rejects_invalid_and_ambiguous_identity(self):
        for phone in ("", "5551234567", "+15551234567\nexport X=bad"):
            with self.assertRaises(ValueError):
                setup.save_identity_phone(self.home, self.backups, phone)
        self.identity.write_text("export OPERATOR_PHONE=''\nexport OPERATOR_PHONE=''\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "multiple"):
            setup.save_identity_phone(self.home, self.backups, PHONE)

    def test_personalized_profile_can_defer_phone(self):
        profile = json.loads((ROOT / "packaging" / "client-profile.example.json").read_text())
        profile.pop("OPERATOR_PHONE")
        source = self.home / "profile.json"
        source.write_text(json.dumps(profile), encoding="utf-8")
        destination = self.home / "personalized.env"
        result = subprocess.run(
            [sys.executable, str(ROOT / "packaging" / "render-profile.py"),
             str(source), str(destination)], capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("export OPERATOR_PHONE=''", destination.read_text())


if __name__ == "__main__":
    unittest.main()
