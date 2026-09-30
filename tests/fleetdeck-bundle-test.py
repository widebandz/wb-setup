#!/usr/bin/env python3
"""Isolated proof that the app payload includes only reviewed Fleetdeck files."""

from __future__ import annotations

import json
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
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
            "launchagents/fleetdeck-chat.plist.tmpl": "__ROOT__/chat_server.py <string>tailscale</string>\n",
            "glyphs.json": '{"server":"<path/>"}\n',
            "make-icons.py": "# generic icon renderer\n",
            "ttyd-index.html": "<!doctype html>\n",
            "assets/icon-180.png": "public icon 180\n",
            "assets/icon-192.png": "public icon 192\n",
            "assets/icon-512.png": "public icon 512\n",
            "icons/server.png": "generic service icon\n",
            "portal_server.py": textwrap.dedent('''\
                from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
                import os, re, json, hmac, stat
                from http.cookies import SimpleCookie
                PAGE = """#cashflow #cashflow #cashflow #cashflow #cashflow
                <a id="netmap" href="__NETMAP__">Live Terminal Network</a>
                <a id="cashflow" href="/cashflow"
                     title="Cashflow — the accountant's cash view">__CASHFLOW_LABEL__</a>"""
                NOTES_PAGE = """ function ago(ts){
                   var s = Math.max(0, Math.floor(Date.now()/1000 - ts));
                }"""
                INTERNAL = {8784}
                SEED_NOTES = [{"title": "Instant iMessage Agent Installer"}]
                OPERATOR_PHONE = os.environ.get("WB_OPERATOR_PHONE", "operator-phone")
                TRACE_IMESSAGE_HANDLE = "operator-apple-account"
                NETMAP_URL = "operator-map"
                CASHFLOW_PATH = "~/finance-ops/cashflow.html"
                WHISPER_MODEL = "operator-model"
                VOICE_URL = "http://127.0.0.1:8890"
                NOTES_PATH = "~/.fleetdeck-notes.json"
                TRACE_SESSION = "trace"
                def scan(): pass
                def onboarding_config(): pass
                class Handler(BaseHTTPRequestHandler):
                    def _send(self, code, body, ctype, extra=None): pass
                    def do_GET(self):
                        path = self.path
                        if path == "/healthz": pass
                    def do_POST(self): pass
                    def _discard_body(self): pass
                    def _board(self): pass
                def main():
                    srv = ThreadingHTTPServer((BIND, PORT), Handler)
                '''),
            "chat_server.py": textwrap.dedent('''\
                import os, re, io, json, time, base64, socket, colorsys, hashlib, signal, stat
                from http.server import BaseHTTPRequestHandler
                def customer_mode(): return True
                BASE = "/t"
                class H(BaseHTTPRequestHandler):
                    def authed(self):
                        return True
                    def try_key(self):
                        return True
                    def do_GET(self):
                        if self.path.startswith("/?key=") and self.try_key():
                            return
                        if not self.authed():
                            return
                        path = self.path.split("?")[0]
                        if path == BASE or path.startswith(BASE + "/"):
                            return self.proxy()
                    def do_POST(self):
                        if not self.authed():
                            return
                    def reply(self, *args):
                        self.send_header("Cache-Control", "no-store")
                    def proxy(self):
                        lines = []
                        buf = b""
                        rest = b""
                        if True:
                            if b" 101 " in lines[0]:
                                self.wfile.write(buf)
                            else:
                                kept = [l for l in lines[1:]
                                        if not re.match(rb"(?i)(connection|keep-alive)\\s*:", l)]
                                self.wfile.write(b"\\r\\n".join([lines[0]] + kept + [b"Connection: close"])
                                                 + b"\\r\\n\\r\\n" + rest)
                if __name__ == "__main__":
                    if customer_mode():
                        print("refusing writable chat in customer mode; use portal /watch", flush=True)
                        raise SystemExit(78)
                '''),
            "test_fleetdeck.py": "operator test\n",
            "README.md": "operator readme\n",
        }
        for name, value in files.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value, encoding="utf-8")
        self.logo = b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isommp42"
        (self.source / bundler.BRAND_VIDEO).write_bytes(self.logo)
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

    def legacy_installed(self, current: Path) -> Path:
        """A prior five-card managed install, for the v1→actual-board upgrade."""
        installed = self.base / "installed-fleetdeck"
        installed.mkdir()
        for name in bundler.LEGACY_REQUIRED:
            source = (ROOT / "packaging" / "customer-portal.py") if name == "portal_server.py" else current / name
            target = installed / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        (installed / "config.example.json").write_text(json.dumps({
            "brand": "fleetdeck", "machine": "", "label_prefix": "com.example",
            "ports": {"portal": 8790, "chat": 8783, "ttyd": 8784, "adopt": 8793},
            "agents": {"show": False, "actions": False, "include": [], "exclude": []},
        }, indent=2) + "\n")
        (installed / "services.example.json").write_text(json.dumps({
            "groups": [{"id": "apps", "label": "apps"}], "services": [],
        }, indent=2) + "\n")
        hashes = {name: hashlib.sha256((installed / name).read_bytes()).hexdigest()
                  for name in bundler.LEGACY_REQUIRED}
        (installed / bundler.MANIFEST).write_text(json.dumps({
            "schema_version": 1, "source": "customer-allowlisted-working-tree",
            "files": hashes,
        }, indent=2, sort_keys=True) + "\n")
        self.run_bundle("verify-managed", str(installed))
        return installed

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
        self.assertIn("CustomerHandler", (target / "portal_server.py").read_text())
        self.assertIn("FLEETDECK_CUSTOMER_TERMINALS", (target / "chat_server.py").read_text())
        self.assertFalse((target / "portal_server.py").read_bytes()
                         == (self.source / "portal_server.py").read_bytes())
        self.assertFalse((target / ".git").exists())
        for name in ("config.json", "services.json", ".fleetdeck-notes.json", "auth", "backups",
                     "test_fleetdeck.py", "README.md"):
            self.assertFalse((target / name).exists(), name)
        manifest = json.loads((target / ".wideband-fleetdeck-bundle.json").read_text())
        self.assertEqual(manifest["source"], "customer-allowlisted-working-tree")
        self.assertEqual(set(manifest["files"]),
                         bundler.REQUIRED | {"icons/server.png", bundler.BRAND_VIDEO})
        self.assertEqual((target / bundler.BRAND_VIDEO).read_bytes(), self.logo)

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

    def test_logo_is_exact_tracked_mp4_and_private_metadata_is_rejected(self) -> None:
        logo = self.source / bundler.BRAND_VIDEO
        target = self.base / "logo-bundle"
        logo.unlink()
        self.assertIn("logo video", self.run_bundle(
            "build", str(self.source), str(target), success=False).stderr)
        self.assertFalse(target.exists())

        logo.write_bytes(b"\x00\x00\x00\x10bad!bad!bad!")
        self.assertIn("not an MP4", self.run_bundle(
            "build", str(self.source), str(target), success=False).stderr)
        self.assertFalse(target.exists())

        logo.write_bytes(self.logo + b"owner@internal.example")
        self.assertIn("operator identifier", self.run_bundle(
            "build", str(self.source), str(target), success=False).stderr)
        self.assertFalse(target.exists())

        logo.write_bytes(self.logo)
        extra = self.source / "assets" / "wb-logo-other.mp4"
        extra.write_bytes(self.logo)
        subprocess.run(["git", "-C", str(self.source), "add", str(extra)], check=True)
        self.run_bundle("build", str(self.source), str(target))
        self.assertTrue((target / bundler.BRAND_VIDEO).is_file())
        self.assertFalse((target / "assets/wb-logo-other.mp4").exists())

    def test_logo_addition_upgrades_old_managed_bundle_and_restores_cleanly(self) -> None:
        current, installed = self.old_and_installed()
        (installed / bundler.BRAND_VIDEO).unlink()
        manifest_path = installed / bundler.MANIFEST
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"].pop(bundler.BRAND_VIDEO)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        (installed / "config.json").write_text('{"client":"keep"}\n')
        self.run_bundle("verify-managed", str(installed))

        result = self.run_bundle("upgrade", str(current), str(installed)).stdout.strip().splitlines()
        self.assertEqual(result[0], "upgraded")
        self.run_bundle("check-current", str(current), str(installed))
        self.assertEqual((installed / bundler.BRAND_VIDEO).read_bytes(), self.logo)
        self.assertEqual((installed / "config.json").read_text(), '{"client":"keep"}\n')

        self.assertEqual(self.run_bundle("restore", str(current), str(installed), result[1]).stdout.strip(),
                         "restored")
        self.run_bundle("verify-managed", str(installed))
        self.assertFalse((installed / bundler.BRAND_VIDEO).exists())
        self.assertEqual((installed / "config.json").read_text(), '{"client":"keep"}\n')

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
        current = self.base / "current-bundle"
        self.run_bundle("build", str(self.source), str(current))
        installed = self.legacy_installed(current)
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
        self.assertIn("outside reviewed managed files", self.run_bundle(
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

    def test_current_fleetdeck_board_and_chat_are_real_and_private(self) -> None:
        source = Path(os.environ.get("FLEETDECK_TEST_SOURCE", ROOT.parent / "fleetdeck"))
        if not (source / ".git").exists():
            self.skipTest("current Fleetdeck checkout is not available")
        bundle = self.base / "actual-board"
        self.run_bundle("build", str(source), str(bundle))
        self.run_bundle("verify", str(bundle))
        logo = bundle / bundler.BRAND_VIDEO
        self.assertEqual(logo.read_bytes(), (source / bundler.BRAND_VIDEO).read_bytes())
        self.assertEqual(logo.stat().st_size, 234_847)
        manifest_files = json.loads((bundle / bundler.MANIFEST).read_text())["files"]
        self.assertEqual(manifest_files[bundler.BRAND_VIDEO],
                         hashlib.sha256(logo.read_bytes()).hexdigest())
        portal_source = (bundle / "portal_server.py").read_text()
        chat_source = (bundle / "chat_server.py").read_text()
        self.assertIn("def scan():", portal_source)
        self.assertIn("CustomerHandler", portal_source)
        self.assertIn("FLEETDECK_CUSTOMER_TERMINALS", chat_source)
        self.assertNotIn('self.path.startswith("/?key=")', chat_source)
        self.assertIsNone(bundler.STATIC_IDENTITY.search(portal_source.encode()))
        self.assertIsNone(bundler.PHONE_IDENTITY.search(portal_source.encode()))
        self.assertNotIn("Instant iMessage Agent Installer", portal_source)
        self.assertIn("return 'saved'", portal_source)
        self.assertIn("<string>127.0.0.1</string>",
                      (bundle / "launchagents/fleetdeck-chat.plist.tmpl").read_text())

        token = self.base / "access-token"
        token.write_text("a" * 64)
        token.chmod(0o600)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        config = json.loads((bundle / "config.example.json").read_text())
        config["ports"]["portal"] = port
        config["onboarding"] = {"os_name": "Test OS", "agent_name": "Test Agent",
                                "first_goal": "website", "head_session": "wb-head"}
        (bundle / "config.json").write_text(json.dumps(config))
        (bundle / "services.json").write_bytes((bundle / "services.example.json").read_bytes())
        env = {**os.environ, "FLEETDECK_ACCESS_TOKEN_PATH": str(token),
               "FLEETDECK_NOTES_PATH": str(self.base / "notes-beta.json"),
               "FLEETDECK_HOST": "client.tail000.ts.net",
               "FLEETDECK_MAP_ORIGIN": "https://client.tail000.ts.net:18970"}

        # A real service scan enables only the two dynamic keys; an empty
        # registry must never make them look live on the client's phone.
        ready_code = "\n".join((
            "import json, sys",
            "sys.path.insert(0, sys.argv[1])",
            "import portal_server as portal",
            "portal.cached_scan = lambda: {'services': json.loads(sys.argv[2])}",
            "portal.customer_map_ready = lambda: sys.argv[3] == 'ready'",
            "handler = portal.CustomerHandler.__new__(portal.CustomerHandler)",
            "handler._send = lambda _status, body, _mime, _extra=None: body",
            "sys.stdout.write(handler._customer_phone())",
        ))
        ready_services = [
            {"id": "chat", "linkable": True,
             "url": "https://client.tail000.ts.net:8783/"},
            {"id": "graph", "linkable": True,
             "url": "https://client.tail000.ts.net:8792/"},
        ]
        def render_ready_phone(services: list[dict] | None = None,
                               map_ready: bool = True) -> subprocess.CompletedProcess[bytes]:
            return subprocess.run([sys.executable, "-c", ready_code, str(bundle),
                                   json.dumps(ready_services if services is None else services),
                                   "ready" if map_ready else "down"],
                                  env={**env, "HOME": str(self.base)},
                                  capture_output=True, timeout=10)

        ready_probe = render_ready_phone()
        self.assertEqual(ready_probe.returncode, 0, ready_probe.stderr.decode())
        self.assertIn(b'<a class="key" href="/app/chat">', ready_probe.stdout)
        self.assertIn(b'<a class="key" href="/app/graph">', ready_probe.stdout)
        self.assertNotIn(b"not ready", ready_probe.stdout)
        self.assertIn(b'href="/agent"', ready_probe.stdout)
        self.assertIn(b"AGENT", ready_probe.stdout)
        self.assertNotIn(b'href="sms:', ready_probe.stdout)
        for bad_url in ("", "https://other.tail000.ts.net:8783/",
                        "https://client.tail000.ts.net:8784/"):
            with self.subTest(chat_url=bad_url):
                bad_services = [{**ready_services[0], "url": bad_url}, ready_services[1]]
                probe = render_ready_phone(bad_services)
                self.assertEqual(probe.returncode, 0, probe.stderr.decode())
                self.assertNotIn(b'href="/app/chat"', probe.stdout)
                self.assertIn(b'<a class="key" href="/app/graph">', probe.stdout)
                self.assertIn(b"not ready", probe.stdout)
        map_down = render_ready_phone(map_ready=False)
        self.assertEqual(map_down.returncode, 0, map_down.stderr.decode())
        self.assertNotIn(b'href="/app/netmap"', map_down.stdout)
        self.assertIn(b'<a class="key" href="/app/chat">', map_down.stdout)

        config_dir = self.base / ".wideband" / "imessage"
        config_dir.mkdir(parents=True, mode=0o700)
        message_config = config_dir / "config.json"
        message_config.write_text(json.dumps({
            "owner_phone": "+15551234567",
            "session": "wb-head", "agent_command": "claude",
            "binding": {"chat_id": 49, "chat_guid": "synthetic-bound-chat",
                        "bound_at": "2026-09-29T12:00:00+00:00",
                        "account_login": "agent@example.invalid"},
        }))
        message_config.chmod(0o600)
        bound_probe = render_ready_phone()
        self.assertEqual(bound_probe.returncode, 0, bound_probe.stderr.decode())
        self.assertIn(b'href="/agent"', bound_probe.stdout)
        self.assertNotIn(b"agent@example.invalid", bound_probe.stdout)
        self.assertNotIn(b'href="sms:', bound_probe.stdout)

        # The private map listener's bare root rejects requests. It must not
        # appear as a tappable unregistered app, while a different listener
        # remains discoverable by Fleetdeck's real scan.
        probe = subprocess.run([sys.executable, "-c", "\n".join((
            "import json, sys",
            "sys.path.insert(0, sys.argv[1])",
            "import portal_server as portal",
            "portal.listeners = lambda: {18790: {'cmd': 'map-probe', 'cls': 'tailnet'}, "
            "4180: {'cmd': 'graph-engine', 'cls': 'host'}, "
            "18791: {'cmd': 'other-probe', 'cls': 'tailnet'}}",
            "portal.serve_map = lambda: {}",
            "portal.launch_agents = lambda: []",
            "print(json.dumps(portal.scan()['extra']))",
        )), str(bundle)], env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertEqual([item["port"] for item in json.loads(probe.stdout)], [18791])

        def request(port: int, path: str, *, cookie: str = "", method: str = "GET",
                    body: bytes | None = None, extra: dict[str, str] | None = None
                    ) -> tuple[int, dict[str, str], bytes]:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            headers = {"Cookie": cookie} if cookie else {}
            headers.update(extra or {})
            if body is not None:
                headers["Content-Type"] = "application/json"
            try:
                conn.request(method, path, body=body, headers=headers)
                response = conn.getresponse()
                return response.status, dict(response.getheaders()), response.read()
            finally:
                conn.close()

        portal = subprocess.Popen([sys.executable, str(bundle / "portal_server.py")],
                                  env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            for _ in range(50):
                try:
                    if request(port, "/healthz")[0] == 200:
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                self.fail("actual Fleetdeck portal did not start")
            self.assertEqual(request(port, "/board")[0], 403)
            status, headers, _ = request(port, "/p/" + "a" * 64 + "/phone")
            self.assertEqual((status, headers.get("Location")), (303, "/phone"))
            self.assertIn("Secure; HttpOnly; SameSite=Strict", headers["Set-Cookie"])
            cookie = headers["Set-Cookie"].split(";", 1)[0]
            status, headers, page = request(port, "/board", cookie=cookie)
            self.assertEqual(status, 200)
            self.assertIn(b"api/status", page)
            self.assertIn(b"/p/" + b"a" * 64 + b"/fleet-map", page)
            self.assertIn(b'<a id="simple" class="" href="/phone"', page)
            self.assertNotIn(b'<a id="cashflow"', page)
            self.assertIn(b'<a id="notes" href="/notes"', page)
            self.assertIn(b'Notes \xce\xb2', page)
            self.assertEqual(headers.get("Referrer-Policy"), "no-referrer")
            status, _, phone = request(port, "/phone", cookie=cookie)
            self.assertEqual(status, 200)
            self.assertIn(b'<div class="clock">', phone)
            self.assertIn(b'<div class="grid">', phone)
            self.assertIn(b'/wb-logo-256.mp4', phone)
            self.assertIn(b'href="/board"', phone)
            self.assertEqual(set(re.findall(rb'<a class="key" href="([^\"]+)"', phone)),
                             {b"/board", b"/project", b"/notes"})
            self.assertEqual(phone.count(b'<a class="key"')
                             + phone.count(b'<span class="key"'), 6)
            self.assertEqual(phone.count(b"not ready"), 3)
            for label in (b"BOARD", b"PROJECT", b"TERMINALS", b"GRAPH", b"NETWORK",
                          "NOTES β".encode()):
                self.assertIn(b"<span>" + label + b"</span>", phone)
            self.assertEqual(request(port, "/wb-logo-256.mp4")[0], 403)
            status, video_headers, video = request(port, "/wb-logo-256.mp4", cookie=cookie)
            self.assertEqual(status, 200)
            self.assertEqual(video_headers.get("Content-Type"), "video/mp4")
            self.assertEqual(len(video), 234_847)
            self.assertEqual(video, logo.read_bytes())
            self.assertEqual(request(port, "/assets/wb-logo-256.mp4", cookie=cookie)[0], 404)
            status, _, api = request(port, "/api/status", cookie=cookie)
            self.assertEqual(status, 200)
            services = json.loads(api)["services"]
            self.assertNotIn("notes", {item["id"] for item in services})
            status, _, graph = request(port, "/graph", cookie=cookie)
            self.assertEqual(status, 200)
            self.assertIn(b"Graph is not running", graph)
            self.assertNotIn(b"Your starter map", graph)
            status, _, manifest = request(port, "/manifest.webmanifest", cookie=cookie)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(manifest)["start_url"], "/p/" + "a" * 64 + "/phone")
            self.assertEqual(request(port, "/api/agent", cookie=cookie,
                                     method="POST", body=b"{}")[0], 404)
            self.assertEqual(request(port, "/p/" + "b" * 64 + "/board")[0], 403)
            status, headers, _ = request(port, "/p/" + "a" * 64 + "/board")
            self.assertEqual((status, headers.get("Location")), (303, "/board"))
            status, _, notes_page = request(port, "/notes", cookie=cookie)
            self.assertEqual(status, 200)
            self.assertIn(b'Notes \xce\xb2', notes_page)
            status, _, created = request(
                port, "/api/notes", cookie=cookie, method="POST",
                body=b'{"text":"Customer note from Fleetdeck board"}',
                extra={"Origin": f"https://client.tail000.ts.net:{port}",
                       "Sec-Fetch-Site": "same-origin"})
            self.assertEqual(status, 200)
            note = json.loads(created)["note"]
            self.assertEqual(note["original"], "Customer note from Fleetdeck board")
            status, _, notes = request(port, "/api/notes", cookie=cookie)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(notes)["notes"][0]["id"], note["id"])
            self.assertEqual(json.loads((self.base / "notes-beta.json").read_text())
                             ["notes"][0]["id"], note["id"])
        finally:
            portal.terminate()
            portal.wait(timeout=5)
            if portal.stderr:
                portal.stderr.close()

        local_env = {**env, "FLEETDECK_HOST": "wideband.localhost",
                     "FLEETDECK_MAP_ORIGIN": "http://wideband.localhost:18790",
                     "FLEETDECK_LOCAL_ONLY": "1"}
        goal_status = self.base / "first-goal-status.json"
        local_env["FLEETDECK_FIRST_GOAL_STATUS_PATH"] = str(goal_status)
        local_host = f"wideband.localhost:{port}"
        local_portal = subprocess.Popen([sys.executable, str(bundle / "portal_server.py")],
                                        env=local_env, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.PIPE)
        try:
            for _ in range(50):
                try:
                    if request(port, "/healthz")[0] == 200:
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                self.fail("local Fleetdeck portal did not start")
            self.assertEqual(request(port, "/board")[0], 403)
            self.assertEqual(request(port, "/p/" + "a" * 64 + "/phone")[0], 403)
            status, headers, _ = request(port, "/p/" + "a" * 64 + "/phone",
                                         extra={"Host": local_host})
            self.assertEqual(status, 303)
            self.assertIn("HttpOnly; SameSite=Strict", headers["Set-Cookie"])
            self.assertNotIn("Secure", headers["Set-Cookie"])
            local_cookie = headers["Set-Cookie"].split(";", 1)[0]
            self.assertEqual(request(port, "/phone", cookie=local_cookie,
                                     extra={"Host": local_host})[0], 200)
            self.assertEqual(request(port, "/board", cookie=local_cookie,
                                     extra={"Host": local_host})[0], 200)
            self.assertEqual(request(port, "/api/notes", cookie=local_cookie,
                                     method="POST", body=b'{"text":"Local idea"}',
                                     extra={"Host": local_host,
                                            "Origin": f"http://{local_host}",
                                            "Sec-Fetch-Site": "same-origin"})[0], 200)
            self.assertEqual(request(port, "/api/notes", cookie=local_cookie,
                                     method="POST", body=b'{"text":"Blocked"}',
                                     extra={"Host": local_host,
                                            "Origin": "http://other.invalid:8790"})[0], 403)

            # The PROJECT key opens a proven local first site on this Mac;
            # the same loopback URL never becomes a phone HTTPS link.
            project_port = None
            for candidate in range(4173, 4200):
                if candidate in (4180, 4181):
                    continue
                with socket.socket() as probe:
                    try:
                        probe.bind(("127.0.0.1", candidate))
                    except OSError:
                        continue
                project_port = candidate
                break
            self.assertIsNotNone(project_port)
            public = self.base / "first-project" / "public"
            public.mkdir(parents=True)
            (public / "index.html").write_text("<title>Actual first project</title>")
            project = subprocess.Popen([
                sys.executable, str(ROOT / "first_goal" / "site_server.py"),
                "--directory", str(public), "--port", str(project_port),
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for _ in range(50):
                    try:
                        if request(project_port, "/health")[0] == 200:
                            break
                    except OSError:
                        time.sleep(0.1)
                else:
                    self.fail("first project preview did not start")
                registry = json.loads((bundle / "services.json").read_text())
                registry["services"].append({"id": "first-project", "port": project_port,
                                             "source": "wideband-first-goal"})
                (bundle / "services.json").write_text(json.dumps(registry))
                local_url = f"http://127.0.0.1:{project_port}/"
                goal = {"goal": "website", "os_name": "Test OS",
                        "agent_name": "Test Agent", "status": "ready",
                        "local_url": local_url}
                goal_status.write_text(json.dumps(goal))
                goal_status.chmod(0o600)
                status, _, project_page = request(port, "/project", cookie=local_cookie,
                                                   extra={"Host": local_host})
                self.assertEqual(status, 200)
                self.assertIn(local_url.encode(), project_page)
                self.assertIn(b"Open on this Mac", project_page)
                self.assertIn(b"Phone access needs a private HTTPS link", project_page)
                self.assertEqual(request(port, "/project", cookie=local_cookie)[0], 403)

                goal["agent_name"] = "Different agent"
                goal_status.write_text(json.dumps(goal))
                self.assertNotIn(local_url.encode(), request(
                    port, "/project", cookie=local_cookie,
                    extra={"Host": local_host})[2])
                goal["agent_name"] = "Test Agent"
                goal["local_url"] = "http://127.0.0.1:4180/"
                goal_status.write_text(json.dumps(goal))
                self.assertNotIn(b"http://127.0.0.1:4180/", request(
                    port, "/project", cookie=local_cookie,
                    extra={"Host": local_host})[2])
                goal["local_url"] = local_url
                goal_status.write_text(json.dumps(goal))
                remote_probe = subprocess.run([sys.executable, "-c", "\n".join((
                    "import sys", "sys.path.insert(0, sys.argv[1])",
                    "import portal_server as portal",
                    "assert portal.customer_local_project_url(portal.onboarding_config()) == ''",
                )), str(bundle)], env={**env, "FLEETDECK_FIRST_GOAL_STATUS_PATH": str(goal_status)},
                    capture_output=True, text=True, timeout=10)
                self.assertEqual(remote_probe.returncode, 0, remote_probe.stderr)
            finally:
                project.terminate()
                project.wait(timeout=5)
            self.assertNotIn(local_url.encode(), request(
                port, "/project", cookie=local_cookie,
                extra={"Host": local_host})[2])
        finally:
            local_portal.terminate()
            local_portal.wait(timeout=5)
            if local_portal.stderr:
                local_portal.stderr.close()

        registry = json.loads((bundle / "services.json").read_text())
        registry["services"].extend([
            {"id": "chat", "port": 8783, "source": "wideband-phone-stack"},
            {"id": "graph", "port": 4181, "source": "wideband-phone-stack"},
        ])
        (bundle / "services.json").write_text(json.dumps(registry))
        local_scan_code = "\n".join((
            "import json, sys",
            "sys.path.insert(0, sys.argv[1])",
            "import portal_server as portal",
            "portal._upstream_cached_scan = lambda: {'services': json.loads(sys.argv[2])}",
            "print(json.dumps(portal.cached_scan()['services']))",
        ))
        local_scan = subprocess.run([sys.executable, "-c", local_scan_code,
                                     str(bundle), json.dumps([
            {"id": "chat", "port": 8783, "up": True, "linkable": False,
             "url": None, "reach": "host"},
            {"id": "graph", "port": 4181, "up": True, "linkable": False,
             "url": None, "reach": "host"},
            {"id": "other", "port": 4182, "up": True, "linkable": False,
             "url": None, "reach": "host"},
        ])], env={**local_env, "HOME": str(self.base)}, capture_output=True,
                                    text=True, timeout=10)
        self.assertEqual(local_scan.returncode, 0, local_scan.stderr)
        local_tiles = {item["id"]: item for item in json.loads(local_scan.stdout)}
        self.assertEqual(local_tiles["chat"]["url"], "/app/chat")
        self.assertEqual(local_tiles["graph"]["url"], "/app/graph")
        self.assertTrue(local_tiles["chat"]["linkable"])
        self.assertFalse(local_tiles["other"]["linkable"])
        remote_scan = subprocess.run([sys.executable, "-c", local_scan_code,
                                      str(bundle), json.dumps([
            {"id": "chat", "port": 8783, "up": True, "linkable": False,
             "url": None, "reach": "host"},
        ])], env={**env, "HOME": str(self.base)}, capture_output=True,
                                     text=True, timeout=10)
        self.assertEqual(remote_scan.returncode, 0, remote_scan.stderr)
        self.assertFalse(json.loads(remote_scan.stdout)[0]["linkable"])
        local_ready = subprocess.run([
            sys.executable, "-c", ready_code, str(bundle), json.dumps([
                {"id": "chat", "up": True, "port": 8783, "linkable": False},
                {"id": "graph", "up": True, "port": 4181, "linkable": False},
            ]), "ready"], env={**local_env, "HOME": str(self.base)},
            capture_output=True, timeout=10)
        self.assertEqual(local_ready.returncode, 0, local_ready.stderr.decode())
        self.assertEqual(local_ready.stdout.count(b'<a class="key"'), 6)
        self.assertIn(b'href="/app/netmap"', local_ready.stdout)
        map_host_probe = subprocess.run([sys.executable, "-c", "\n".join((
            "import json, sys",
            "sys.path.insert(0, sys.argv[1])",
            "import portal_server as portal",
            "class Response:",
            "    status = 200",
            "    def getheader(self, _name, _default=''): return 'application/json'",
            "    def read(self, _max_bytes): return json.dumps({'schema_version': 'agent-fleet.snapshot.v1', 'nodes': [], 'summary': {'live_sessions': 0}}).encode()",
            "class Connection:",
            "    def __init__(self, host, port, timeout): assert (host, port) == ('127.0.0.1', 18790)",
            "    def request(self, method, path, headers): assert headers == {'Host': 'wideband.localhost:18790'}",
            "    def getresponse(self): return Response()",
            "    def close(self): pass",
            "portal.http.client.HTTPConnection = Connection",
            "assert portal.customer_map_ready()",
        )), str(bundle)], env={**local_env, "HOME": str(self.base)},
                                    capture_output=True, text=True, timeout=10)
        self.assertEqual(map_host_probe.returncode, 0, map_host_probe.stderr)

        disabled = subprocess.run([sys.executable, str(bundle / "chat_server.py")],
                                  env={**env, "BIND": "127.0.0.1"},
                                  capture_output=True, timeout=5)
        self.assertEqual(disabled.returncode, 78)
        missing_host_env = {**env, "BIND": "127.0.0.1",
                            "FLEETDECK_CUSTOMER_TERMINALS": "1"}
        missing_host_env.pop("FLEETDECK_HOST")
        missing_host = subprocess.run([sys.executable, str(bundle / "chat_server.py")],
                                      env=missing_host_env, capture_output=True, timeout=5)
        self.assertEqual(missing_host.returncode, 78)
        unsafe_host = subprocess.run([sys.executable, str(bundle / "chat_server.py")],
                                     env={**missing_host_env, "FLEETDECK_HOST":
                                          "client.tail000.ts.net.evil.invalid"},
                                     capture_output=True, timeout=5)
        self.assertEqual(unsafe_host.returncode, 78)

        class TtydFixture(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/t/ws":
                    self.send_response(101)
                    self.send_header("Connection", "Upgrade")
                    self.send_header("Upgrade", "websocket")
                    self.send_header("X-Frame-Options", "DENY")
                    self.send_header("Content-Security-Policy", "default-src 'none'; "
                                     "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
                    self.end_headers()
                    self.close_connection = True
                    return
                payload = b"private ttyd fixture"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Content-Security-Policy", "default-src 'none'; "
                                 "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format: str, *args: object) -> None:
                pass

        ttyd = ThreadingHTTPServer(("127.0.0.1", 0), TtydFixture)
        ttyd_thread = threading.Thread(target=ttyd.serve_forever, daemon=True)
        ttyd_thread.start()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            chat_port = listener.getsockname()[1]
        code = ("import sys; sys.path.insert(0, sys.argv[1]); "
                "from http.server import ThreadingHTTPServer; import chat_server; "
                "ThreadingHTTPServer(('127.0.0.1', int(sys.argv[2])), chat_server.H).serve_forever()")
        chat = subprocess.Popen([sys.executable, "-c", code, str(bundle), str(chat_port)],
                                env={**env, "TTYD_PORT": str(ttyd.server_port)},
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            for _ in range(50):
                try:
                    if request(chat_port, "/")[0] == 403:
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                self.fail("actual Fleetdeck chat handler did not start")
            self.assertEqual(request(chat_port, "/?key=old-bypass")[0], 403)
            self.assertEqual(request(chat_port, "/t/ws")[0], 403)
            self.assertEqual(request(chat_port, "/api/send", method="POST", body=b"{}")[0], 403)
            with socket.create_connection(("127.0.0.1", chat_port), timeout=5) as raw:
                raw.sendall(("GET /p/" + "a" * 64 + "/chat HTTP/1.0\r\n"
                             "Host: 127.0.0.1\r\n\r\n").encode("ascii"))
                response = bytearray()
                while chunk := raw.recv(4096):
                    response.extend(chunk)
            header = bytes(response).split(b"\r\n\r\n", 1)[0]
            self.assertEqual(header.count(b"HTTP/1.0 303"), 1)
            self.assertEqual(header.count(b"Set-Cookie:"), 1)
            self.assertEqual(header.count(b"Location: /"), 1)
            status, headers, _ = request(chat_port, "/p/" + "a" * 64 + "/chat")
            self.assertEqual((status, headers.get("Location")), (303, "/"))
            chat_cookie = headers["Set-Cookie"].split(";", 1)[0]
            self.assertEqual(chat_cookie, cookie)
            status, headers, _ = request(chat_port, "/", cookie=chat_cookie)
            self.assertEqual(status, 200)
            self.assertEqual(headers.get("Content-Security-Policy"),
                             "frame-ancestors 'self' https://client.tail000.ts.net:8790")
            status, headers, body = request(chat_port, "/t/", cookie=chat_cookie)
            self.assertEqual((status, body), (200, b"private ttyd fixture"))
            self.assertEqual(headers.get("Content-Security-Policy"),
                             "frame-ancestors 'self' https://client.tail000.ts.net:8790")
            self.assertNotIn("X-Frame-Options", headers)
            with socket.create_connection(("127.0.0.1", chat_port), timeout=5) as raw:
                raw.sendall(("GET /t/ HTTP/1.0\r\n"
                             f"Host: 127.0.0.1:{chat_port}\r\n"
                             f"Cookie: {chat_cookie}\r\n\r\n").encode("ascii"))
                response_head = bytearray()
                while b"\r\n\r\n" not in response_head:
                    chunk = raw.recv(4096)
                    if not chunk:
                        break
                    response_head.extend(chunk)
            self.assertIn(b"Content-Security-Policy: default-src 'none'; "
                          b"connect-src 'self'; base-uri 'none'", response_head)
            self.assertIn(b"Content-Security-Policy: frame-ancestors 'self' "
                          b"https://client.tail000.ts.net:8790", response_head)
            with socket.create_connection(("127.0.0.1", chat_port), timeout=5) as raw:
                raw.sendall(("GET /t/ws HTTP/1.1\r\n"
                             f"Host: 127.0.0.1:{chat_port}\r\n"
                             f"Cookie: {chat_cookie}\r\n"
                             "Connection: Upgrade\r\n"
                             "Upgrade: websocket\r\n\r\n").encode("ascii"))
                response_head = bytearray()
                while b"\r\n\r\n" not in response_head:
                    chunk = raw.recv(4096)
                    if not chunk:
                        break
                    response_head.extend(chunk)
            self.assertIn(b"HTTP/1.0 101", response_head)
            self.assertIn(b"Connection: Upgrade", response_head)
            self.assertIn(b"Content-Security-Policy: frame-ancestors 'self' "
                          b"https://client.tail000.ts.net:8790", response_head)
            self.assertIn(b"Content-Security-Policy: default-src 'none'; "
                          b"connect-src 'self'; base-uri 'none'", response_head)
            self.assertNotIn(b"X-Frame-Options", response_head)
            self.assertEqual(request(chat_port, "/api/send", cookie=chat_cookie,
                                     method="POST", body=b"{}",
                                     extra={"Origin": "https://other.tail000.ts.net:8783"})[0], 403)
            self.assertEqual(request(chat_port, "/t/ws", cookie=chat_cookie,
                                     extra={"Upgrade": "websocket",
                                            "Origin": "https://other.tail000.ts.net:8783"})[0], 403)

            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                local_chat_port = listener.getsockname()[1]
            local_chat = subprocess.Popen(
                [sys.executable, "-c", code, str(bundle), str(local_chat_port)],
                env={**local_env, "BIND": "127.0.0.1",
                     "PORT": str(local_chat_port), "TTYD_PORT": str(ttyd.server_port),
                     "FLEETDECK_CUSTOMER_TERMINALS": "1"},
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                for _ in range(50):
                    try:
                        if request(local_chat_port, "/")[0] == 403:
                            break
                    except OSError:
                        time.sleep(0.1)
                else:
                    self.fail("local Fleetdeck terminal did not start")
                chat_host = f"wideband.localhost:{local_chat_port}"
                self.assertEqual(request(local_chat_port, "/p/" + "a" * 64 + "/chat")[0], 403)
                status, headers, _ = request(local_chat_port, "/p/" + "a" * 64 + "/chat",
                                             extra={"Host": chat_host})
                self.assertEqual(status, 303)
                self.assertIn("HttpOnly; SameSite=Strict", headers["Set-Cookie"])
                self.assertNotIn("Secure", headers["Set-Cookie"])
                cookie = headers["Set-Cookie"].split(";", 1)[0]
                status, headers, _ = request(local_chat_port, "/", cookie=cookie,
                                             extra={"Host": chat_host})
                self.assertEqual(status, 200)
                self.assertEqual(headers["Content-Security-Policy"],
                                 "frame-ancestors 'self' http://wideband.localhost:8790")
                self.assertEqual(request(local_chat_port, "/api/unknown", cookie=cookie,
                                         method="POST", body=b"{}",
                                         extra={"Host": chat_host,
                                                "Origin": f"http://{chat_host}",
                                                "Sec-Fetch-Site": "same-origin"})[0], 404)
                self.assertEqual(request(local_chat_port, "/api/send", cookie=cookie,
                                         method="POST", body=b"{}",
                                         extra={"Host": chat_host,
                                                "Origin": "http://other.invalid:8783"})[0], 403)
            finally:
                local_chat.terminate()
                local_chat.wait(timeout=5)
                if local_chat.stderr:
                    local_chat.stderr.close()
        finally:
            chat.terminate()
            chat.wait(timeout=5)
            if chat.stderr:
                chat.stderr.close()
            ttyd.shutdown()
            ttyd.server_close()
            ttyd_thread.join(timeout=5)

    def test_actual_board_upgrade_adds_files_without_changing_client_data(self) -> None:
        source = Path(os.environ.get("FLEETDECK_TEST_SOURCE", ROOT.parent / "fleetdeck"))
        if not (source / ".git").exists():
            self.skipTest("current Fleetdeck checkout is not available")
        current = self.base / "actual-board"
        self.run_bundle("build", str(source), str(current))
        installed = self.legacy_installed(current)
        (installed / "config.json").write_text('{"client":"keep"}\n')
        (installed / "services.json").write_text('{"services":[]}\n')
        (installed / "notes-beta.json").write_text('{"notes":[{"id":"keep"}]}\n')
        result = self.run_bundle("upgrade", str(current), str(installed)).stdout.strip().splitlines()
        self.assertEqual(result[0], "upgraded")
        self.run_bundle("verify-managed", str(installed))
        self.run_bundle("check-current", str(current), str(installed))
        self.assertTrue((installed / "customer_access.py").exists())
        self.assertTrue((installed / "glyphs.json").exists())
        self.assertEqual((installed / "config.json").read_text(), '{"client":"keep"}\n')
        self.assertEqual((installed / "notes-beta.json").read_text(),
                         '{"notes":[{"id":"keep"}]}\n')
        self.run_bundle("restore", str(current), str(installed), result[1])
        self.run_bundle("verify-managed", str(installed))
        self.assertFalse((installed / "customer_access.py").exists())
        self.assertEqual((installed / "notes-beta.json").read_text(),
                         '{"notes":[{"id":"keep"}]}\n')


if __name__ == "__main__":
    unittest.main()
