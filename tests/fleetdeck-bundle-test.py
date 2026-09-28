#!/usr/bin/env python3
"""Isolated proof that the app payload includes only reviewed Fleetdeck files."""

from __future__ import annotations

import json
import hashlib
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BUNDLER = ROOT / "packaging" / "bundle-fleetdeck.py"
TOKEN_HELPER = ROOT / "packaging" / "phone-access-token.py"
SPEC = importlib.util.spec_from_file_location("fleetdeck_bundler_test", BUNDLER)
bundler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundler)


class FleetdeckBundleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="wb-fleetdeck-bundle-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.source = self.base / "fleetdeck"
        self.source.mkdir()
        subprocess.run(["git", "init", "-q", str(self.source)], check=True)
        files = {
            "install.sh": "#!/bin/sh\nCUSTOMER_MODE=1\n",
            "bin/fleetdeck": "#!/bin/sh\n",
            "VERSION": "0.1\n",
            "LICENSE": "public license\n",
            "NOTICE": "public notice\n",
            "launchagents/fleetdeck-portal.plist.tmpl": "__ROOT__/portal_server.py\n",
            "assets/icon-192.png": "public icon 192\n",
            "assets/icon-512.png": "public icon 512\n",
            # A tracked operator portal is deliberately excluded from the bundle.
            "portal_server.py": "operator portal: owner@internal.example\n",
            "test_fleetdeck.py": "operator test\n",
            "README.md": "operator readme\n",
        }
        for name, value in files.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value, encoding="utf-8")
        subprocess.run(["git", "-C", str(self.source), "add", "."], check=True)

    def run_bundle(self, *args: str, success: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run([sys.executable, str(BUNDLER), *args],
                                capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def portal_update(self, old: Path) -> Path:
        newer = self.base / "newer-portal-bundle"
        shutil.copytree(old, newer)
        portal = newer / "portal_server.py"
        portal.write_bytes(portal.read_bytes() + b"\n# reviewed customer board update\n")
        manifest_path = newer / ".wideband-fleetdeck-bundle.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"]["portal_server.py"] = hashlib.sha256(portal.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.run_bundle("verify", str(newer))
        return newer

    def old_and_installed(self) -> tuple[Path, Path]:
        old = self.base / "old-bundle"
        self.run_bundle("build", str(self.source), str(old))
        installed = self.base / "installed-fleetdeck"
        shutil.copytree(old, installed)
        return old, installed

    def test_tracked_working_tree_is_bundled_without_local_data(self) -> None:
        (self.source / "install.sh").write_text(
            '#!/bin/sh\nCUSTOMER_MODE=1\n# reviewed working-tree change\n', encoding="utf-8")
        (self.source / "config.json").write_text('{"private":"client"}\n', encoding="utf-8")
        (self.source / "services.json").write_text("client board\n", encoding="utf-8")
        (self.source / ".fleetdeck-notes.json").write_text("private notes\n", encoding="utf-8")
        (self.source / "auth").write_text("secret\n", encoding="utf-8")
        (self.source / "backups").mkdir()
        (self.source / "backups" / "config.json.bak").write_text("old secret\n", encoding="utf-8")

        target = self.base / "payload" / "vendor" / "fleetdeck"
        self.run_bundle("build", str(self.source), str(target))
        self.run_bundle("verify", str(target))
        self.assertIn("reviewed working-tree change", (target / "install.sh").read_text())
        self.assertIn("def onboarding_config", (target / "portal_server.py").read_text())
        self.assertFalse((target / "portal_server.py").read_bytes()
                         == (self.source / "portal_server.py").read_bytes())
        self.assertFalse((target / ".git").exists())
        for name in ("config.json", "services.json", ".fleetdeck-notes.json", "auth", "backups",
                     "test_fleetdeck.py", "README.md"):
            self.assertFalse((target / name).exists(), name)
        manifest = json.loads((target / ".wideband-fleetdeck-bundle.json").read_text())
        self.assertEqual(manifest["source"], "customer-allowlisted-working-tree")
        self.assertEqual(set(manifest["files"]), {
            "install.sh", "bin/fleetdeck", "VERSION", "LICENSE", "NOTICE",
            "portal_server.py", "config.example.json",
            "services.example.json", "launchagents/fleetdeck-portal.plist.tmpl",
            "assets/icon-192.png", "assets/icon-512.png",
        })

        installed = self.base / "installed-fleetdeck"
        shutil.copytree(target, installed)
        (installed / "config.json").write_text('{"brand":"Client"}\n', encoding="utf-8")
        (installed / "services.json").write_text('{"services": []}\n', encoding="utf-8")
        (installed / "auth").write_text("private token\n", encoding="utf-8")
        self.run_bundle("verify-managed", str(installed))
        self.run_bundle("check-current", str(target), str(installed))
        (self.source / "install.sh").write_text(
            '#!/bin/sh\nCUSTOMER_MODE=1\n# newer release\n', encoding="utf-8")
        newer = self.base / "newer-bundle"
        self.run_bundle("build", str(self.source), str(newer))
        self.assertIn("review upgrade", self.run_bundle(
            "check-current", str(newer), str(installed), success=False).stderr)
        self.assertEqual((installed / "config.json").read_text(), '{"brand":"Client"}\n')
        (installed / "portal_server.py").write_text("client edit\n", encoding="utf-8")
        self.assertIn("checksum mismatch", self.run_bundle(
            "verify-managed", str(installed), success=False).stderr)

        (target / "portal_server.py").write_text("tampered\n", encoding="utf-8")
        self.assertIn("checksum mismatch", self.run_bundle("verify", str(target), success=False).stderr)

    def test_tracked_private_file_fails_build(self) -> None:
        (self.source / "config.json").write_text("secret\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.source), "add", "config.json"], check=True)
        target = self.base / "bad-bundle"
        self.assertIn("unsafe", self.run_bundle("build", str(self.source), str(target),
                                                 success=False).stderr)
        self.assertFalse(target.exists())

    def test_tracked_symlink_fails_build(self) -> None:
        (self.source / "external").symlink_to("/etc/hosts")
        subprocess.run(["git", "-C", str(self.source), "add", "external"], check=True)
        target = self.base / "bad-link-bundle"
        self.assertIn("unsafe", self.run_bundle("build", str(self.source), str(target),
                                                 success=False).stderr)
        self.assertFalse(target.exists())

    def test_private_identifier_in_selected_file_fails_build(self) -> None:
        (self.source / "install.sh").write_text(
            "#!/bin/sh\nCUSTOMER_MODE=1\n# owner@internal.example\n", encoding="utf-8")
        target = self.base / "unsafe-bundle"
        self.assertIn("operator identifier", self.run_bundle(
            "build", str(self.source), str(target), success=False).stderr)
        self.assertFalse(target.exists())

    def test_portal_only_upgrade_preserves_client_data_and_keeps_backup(self) -> None:
        old, installed = self.old_and_installed()
        newer = self.portal_update(old)
        private = {
            "config.json": b'{"brand":"Client"}\n',
            "services.json": b'{"services":[{"id":"first-project"}]}\n',
            "auth": b"private credential\n",
            ".fleetdeck-notes.json": b"private notes\n",
            "notes/review.txt": b"client note\n",
            "other/client.txt": b"client work\n",
        }
        for name, content in private.items():
            path = installed / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        old_portal = (installed / "portal_server.py").read_bytes()
        old_manifest = (installed / ".wideband-fleetdeck-bundle.json").read_bytes()
        result = self.run_bundle("upgrade", str(newer), str(installed)).stdout.strip().splitlines()
        self.assertEqual(result[0], "upgraded")
        self.assertEqual(len(result), 2)
        self.assertTrue(Path(result[1]).is_dir())
        self.run_bundle("verify-managed", str(installed))
        self.run_bundle("check-current", str(newer), str(installed))
        self.assertEqual((installed / "portal_server.py").read_bytes(), (newer / "portal_server.py").read_bytes())
        for name, content in private.items():
            self.assertEqual((installed / name).read_bytes(), content, name)
        backups = list(self.base.glob(".installed-fleetdeck-upgrade-backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "portal_server.py").read_bytes(), old_portal)
        self.assertEqual((backups[0] / ".wideband-fleetdeck-bundle.json").read_bytes(), old_manifest)
        self.assertEqual(self.run_bundle("upgrade", str(newer), str(installed)).stdout.strip(), "current")
        self.assertEqual(len(list(self.base.glob(".installed-fleetdeck-upgrade-backup-*"))), 1)

        self.assertEqual(self.run_bundle("restore", str(newer), str(installed), result[1]).stdout.strip(),
                         "restored")
        self.run_bundle("verify-managed", str(installed))
        self.assertEqual((installed / "portal_server.py").read_bytes(), old_portal)
        self.assertEqual((installed / ".wideband-fleetdeck-bundle.json").read_bytes(), old_manifest)
        for name, content in private.items():
            self.assertEqual((installed / name).read_bytes(), content, name)

    def test_upgrade_accepts_previous_health_route_marker(self) -> None:
        current, installed = self.old_and_installed()
        old_portal = installed / "portal_server.py"
        old_source = old_portal.read_text(encoding="utf-8")
        self.assertIn('raw_path == "/healthz"', old_source)
        old_portal.write_text(old_source.replace('raw_path == "/healthz"',
                                                 'route == "/healthz"', 1), encoding="utf-8")
        manifest_path = installed / ".wideband-fleetdeck-bundle.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"]["portal_server.py"] = hashlib.sha256(old_portal.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        self.run_bundle("verify-managed", str(installed))
        result = self.run_bundle("upgrade", str(current), str(installed)).stdout.strip().splitlines()
        self.assertEqual(result[0], "upgraded")
        self.run_bundle("check-current", str(current), str(installed))
        self.assertEqual((installed / "portal_server.py").read_bytes(),
                         (current / "portal_server.py").read_bytes())
        self.run_bundle("restore", str(current), str(installed), result[1])
        self.run_bundle("verify-managed", str(installed))
        self.assertIn('route == "/healthz"', old_portal.read_text(encoding="utf-8"))

    def test_restore_refuses_wrong_backup_or_changed_source(self) -> None:
        old, installed = self.old_and_installed()
        newer = self.portal_update(old)
        result = self.run_bundle("upgrade", str(newer), str(installed)).stdout.strip().splitlines()
        backup = Path(result[1])
        wrong = self.base / "wrong-backup"
        wrong.symlink_to(backup, target_is_directory=True)
        self.assertIn("unsafe", self.run_bundle(
            "restore", str(newer), str(installed), str(wrong), success=False).stderr)
        (installed / "portal_server.py").write_text("client edit after upgrade\n", encoding="utf-8")
        self.assertIn("checksum mismatch", self.run_bundle(
            "restore", str(newer), str(installed), str(backup), success=False).stderr)
        self.assertEqual((installed / "portal_server.py").read_text(), "client edit after upgrade\n")

    def test_phone_access_token_is_private_stable_and_refuses_unsafe_existing_file(self) -> None:
        home = self.base / "customer"
        home.mkdir()

        def prepare(success: bool = True) -> subprocess.CompletedProcess[str]:
            result = subprocess.run([sys.executable, str(TOKEN_HELPER), str(home)],
                                    capture_output=True, text=True)
            if success:
                self.assertEqual(result.returncode, 0, result.stderr)
            else:
                self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("phone-access-token", result.stdout)
            return result

        prepare()
        parent = home / ".wideband" / "fleetdeck"
        token = parent / "phone-access-token"
        original = token.read_bytes()
        self.assertRegex(original.decode(), r"^[0-9a-f]{64}$")
        self.assertEqual(parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(token.stat().st_mode & 0o777, 0o600)
        prepare()
        self.assertEqual(token.read_bytes(), original)
        token.chmod(0o644)
        self.assertIn("unsafe", prepare(success=False).stderr)
        self.assertEqual(token.read_bytes(), original)
        token.unlink()
        token.symlink_to(home / "somewhere-else")
        prepare(success=False)
        self.assertTrue(token.is_symlink())

    def test_upgrade_refuses_other_bundle_changes_and_client_edits(self) -> None:
        old, installed = self.old_and_installed()
        newer = self.portal_update(old)
        original_portal = (installed / "portal_server.py").read_bytes()
        original_manifest = (installed / ".wideband-fleetdeck-bundle.json").read_bytes()

        modified_package = self.base / "modified-package"
        shutil.copytree(newer, modified_package)
        installer = modified_package / "install.sh"
        installer.write_bytes(installer.read_bytes() + b"\n# unrelated change\n")
        manifest_path = modified_package / ".wideband-fleetdeck-bundle.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"]["install.sh"] = hashlib.sha256(installer.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.assertIn("outside the generated portal", self.run_bundle(
            "upgrade", str(modified_package), str(installed), success=False).stderr)
        self.assertEqual((installed / "portal_server.py").read_bytes(), original_portal)
        self.assertEqual((installed / ".wideband-fleetdeck-bundle.json").read_bytes(), original_manifest)

        (installed / "portal_server.py").write_text("client-edited source\n", encoding="utf-8")
        self.assertIn("checksum mismatch", self.run_bundle(
            "upgrade", str(newer), str(installed), success=False).stderr)
        (installed / "portal_server.py").unlink()
        (installed / "portal_server.py").symlink_to(old / "portal_server.py")
        self.assertIn("checksum mismatch", self.run_bundle(
            "upgrade", str(newer), str(installed), success=False).stderr)
        (installed / "portal_server.py").unlink()
        shutil.copy2(old / "portal_server.py", installed / "portal_server.py")
        (installed / "bin/fleetdeck").write_text("client-edited CLI\n", encoding="utf-8")
        self.assertIn("checksum mismatch", self.run_bundle(
            "upgrade", str(newer), str(installed), success=False).stderr)

    def test_failed_manifest_replacement_rolls_back_portal(self) -> None:
        old, installed = self.old_and_installed()
        newer = self.portal_update(old)
        private = installed / "config.json"
        private.write_bytes(b"owner config\n")
        original_portal = (installed / "portal_server.py").read_bytes()
        original_manifest = (installed / ".wideband-fleetdeck-bundle.json").read_bytes()
        real_replace = bundler.os.replace
        failed = False

        def fail_once(source: Path, destination: Path) -> None:
            nonlocal failed
            if Path(destination) == installed / bundler.MANIFEST and not failed:
                failed = True
                raise OSError("injected manifest replacement failure")
            real_replace(source, destination)

        with mock.patch.object(bundler.os, "replace", side_effect=fail_once):
            with self.assertRaisesRegex(ValueError, "previous source preserved"):
                bundler.upgrade(newer, installed)
        self.assertTrue(failed)
        self.run_bundle("verify-managed", str(installed))
        self.assertEqual((installed / "portal_server.py").read_bytes(), original_portal)
        self.assertEqual((installed / bundler.MANIFEST).read_bytes(), original_manifest)
        self.assertEqual(private.read_bytes(), b"owner config\n")
        self.assertFalse([path for path in installed.glob(".wideband-fleetdeck-*")
                          if path.name != bundler.MANIFEST])


if __name__ == "__main__":
    unittest.main()
