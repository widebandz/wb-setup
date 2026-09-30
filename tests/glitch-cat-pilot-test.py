#!/usr/bin/env python3
"""Checks that the pilot indexes only a declared local corpus."""

from __future__ import annotations

import errno
import importlib.util
import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from unittest import mock
import urllib.error
import urllib.request


SCRIPT = Path(__file__).resolve().parents[1] / "packaging" / "glitch-cat-pilot.py"
SPEC = importlib.util.spec_from_file_location("glitch_cat_pilot", SCRIPT)
pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot)


class GlitchCatPilotTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="wb-graph-pilot-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.source = self.base / "source"
        self.source.mkdir()
        subprocess.run(["git", "init", "-q", str(self.source)], check=True)
        files = pilot.REQUIRED | pilot.ICON_NAMES | {
            "engine/query.mjs", "engine/cli.test.mjs", "packs/wideband/roots.yaml",
            "packs/wideband/register/claims.yaml", ".data/kg.db", "README.md",
        }
        for name in files:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if name == "package.json":
                data = json.dumps({"scripts": {"graph": "node engine/cli.mjs",
                                               "serve": "node engine/serve.mjs"}})
            elif name == "engine/serve.mjs":
                data = ('const deck="https://sample-agent.tailnet123.ts.net:8790"; '
                        'const title="sample-agent // health";\n'
                        + pilot.GRAPH_STYLE_MARKER + '\n'
                        + '<div id="side">\n' + pilot.GRAPH_STAGE_MARKER + '\n'
                        + pilot.DEFAULT_LENS_SOURCE + pilot.GRAPH_SCRIPT_MARKER + '\n'
                        + pilot.GRAPH_SERVER_MARKER)
            elif name == "engine/cli.mjs":
                data = pilot.TAILSCALE_SOURCE
            elif name == "engine/types.mjs":
                data = 'const owner="owner@private.example";'
            else:
                data = "generic fixture\n"
            path.write_text(data, encoding="utf-8")
        subprocess.run(["git", "-C", str(self.source), "add", "."], check=True)
        (self.source / "host-secret.json").write_text("secret", encoding="utf-8")

    def bundled(self) -> Path:
        bundle = self.base / "bundle"
        pilot.bundle(self.source, bundle)
        return bundle

    def test_graph_uses_only_verified_node_and_npm(self) -> None:
        toolbin = self.base / "private" / "bin"
        toolbin.mkdir(parents=True)
        for name in ("node", "npm"):
            (toolbin / name).write_text("tool")
        answer = subprocess.CompletedProcess([], 0, str(toolbin / "node") + "\n", "")
        with mock.patch.object(pilot.subprocess, "run", return_value=answer) as resolve, \
             mock.patch.object(pilot.subprocess, "check_output", return_value="v24.21.0\n"):
            self.assertEqual(pilot.node_path(), str(toolbin / "node"))
        resolve.assert_called_once_with([str(pilot.TOOLCHAIN_RESOLVER), "node"],
                                        capture_output=True, text=True, timeout=30)
        self.assertEqual(pilot.runtime_env(self.base, str(toolbin / "node"))["PATH"],
                         f"{toolbin}:/usr/bin:/bin:/usr/sbin:/sbin")
        with mock.patch.object(pilot.subprocess, "run", return_value=
                               subprocess.CompletedProcess([], 1, "", "missing")):
            with self.assertRaisesRegex(ValueError, "verified node"):
                pilot.node_path()

        other_bin = self.base / "other" / "bin"
        other_bin.mkdir(parents=True)
        (other_bin / "npm").write_text("tool")
        with mock.patch.object(pilot, "preflight", return_value=str(toolbin / "node")), \
             mock.patch.object(pilot, "port_free"), \
             mock.patch.object(pilot, "tool_path", return_value=str(other_bin / "npm")):
            with self.assertRaisesRegex(ValueError, "different installations"):
                pilot.build(self.base)

    def test_only_tracked_engine_package_and_icons_ship(self) -> None:
        bundle = self.bundled()
        hashes = pilot.verify(bundle)
        self.assertIn("engine/query.mjs", hashes)
        self.assertNotIn("engine/cli.test.mjs", hashes)
        self.assertFalse((bundle / "packs").exists())
        self.assertFalse((bundle / ".data").exists())
        self.assertFalse((bundle / "README.md").exists())
        self.assertFalse((bundle / "host-secret.json").exists())
        self.assertIn("@example.test", (bundle / "engine/types.mjs").read_text())
        self.assertNotIn("owner@private.example", (bundle / "engine/types.mjs").read_text())
        self.assertNotIn("sample-agent", (bundle / "engine/serve.mjs").read_text())
        self.assertIn(pilot.DEFAULT_LENS_PILOT, (bundle / "engine/serve.mjs").read_text())
        self.assertIn('id="mobile-lenses"', (bundle / "engine/serve.mjs").read_text())
        self.assertIn("req.headers.host !== `127.0.0.1:${PORT}`",
                      (bundle / "engine/serve.mjs").read_text())
        self.assertIn("/Applications/Tailscale.app/Contents/MacOS/Tailscale",
                      (bundle / "engine/cli.mjs").read_text())

    def test_bundle_detects_tampering_and_unexpected_files(self) -> None:
        bundle = self.bundled()
        (bundle / "engine/cli.mjs").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "changed"):
            pilot.verify(bundle)
        bundle = self.base / "bundle-two"
        pilot.bundle(self.source, bundle)
        (bundle / "packs").mkdir()
        (bundle / "packs" / "host.yaml").write_text("private")
        with self.assertRaisesRegex(ValueError, "unexpected"):
            pilot.verify(bundle)

    def test_stage_is_private_and_never_replaces_client_tree(self) -> None:
        bundle = self.bundled()
        target = self.base / "installed"
        pilot.stage(bundle, target)
        pilot.verify(target, staged=True)
        self.assertEqual(target.stat().st_mode & 0o777, 0o700)
        self.assertEqual((target / ".data").stat().st_mode & 0o777, 0o700)
        self.assertIn("~/wideband/first-project", (target / "packs" / pilot.PACK / "roots.yaml").read_text())
        self.assertIn("zones:", (target / "packs" / pilot.PACK / "conventions.yaml").read_text())
        sentinel = target / "client-data.txt"
        sentinel.write_text("keep me")
        with self.assertRaisesRegex(ValueError, "target exists"):
            pilot.stage(bundle, target)
        self.assertEqual(sentinel.read_text(), "keep me")

    def test_preflight_checks_real_roots_and_declared_pack(self) -> None:
        bundle = self.bundled()
        target = self.base / "installed"
        pilot.stage(bundle, target)
        home = self.base / "home"
        (home / "srv" / "wb-setup").mkdir(parents=True)
        (home / "wideband" / "first-project").mkdir(parents=True)
        with mock.patch.object(pilot.Path, "home", return_value=home), \
                mock.patch.object(pilot, "node_path", return_value="/bin/node"):
            self.assertEqual(pilot.preflight(target), "/bin/node")
            (target / "packs" / pilot.PACK / "roots.yaml").write_text("changed")
            with self.assertRaisesRegex(ValueError, "corpus declaration changed"):
                pilot.preflight(target)


    def test_other_tailnet_url_is_sanitized(self) -> None:
        (self.source / "engine" / "query.mjs").write_text(
            "const hidden='https://another.tailnet789.ts.net/path'", encoding="utf-8")
        bad = self.base / "sanitized-bundle"
        pilot.bundle(self.source, bad)
        self.assertNotIn("tailnet789", (bad / "engine/query.mjs").read_text())

    def test_bundled_viewer_rejects_foreign_host_before_api(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is needed for the HTTP boundary test")
        source = ("import { createServer } from 'node:http'\n"
                  "const PORT = Number(process.argv[2])\n"
                  "const html = `<style>" + pilot.GRAPH_STYLE_MARKER
                  + '<div id="side">' + pilot.GRAPH_STAGE_MARKER
                  + pilot.GRAPH_SCRIPT_MARKER + '`\n'
                  + pilot.DEFAULT_LENS_SOURCE + '\n'
                  + pilot.GRAPH_SERVER_MARKER + "\n"
                  "    res.writeHead(200, { 'content-type': 'application/json' })\n"
                  "    return res.end(JSON.stringify({ private: true, path: url.pathname }))\n"
                  "  } catch (error) { res.writeHead(500); res.end(String(error)) }\n"
                  "}).listen(PORT, '127.0.0.1')\n")
        file = self.base / "viewer.mjs"
        file.write_bytes(pilot.sanitized_bytes("engine/serve.mjs", source.encode()))
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        proc = subprocess.Popen([node, str(file), str(port)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        def stop_viewer() -> None:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=2)
            proc.stderr.close()
        self.addCleanup(stop_viewer)
        base = f"http://127.0.0.1:{port}/api/stats"
        for _ in range(40):
            try:
                with urllib.request.urlopen(base, timeout=0.2) as response:
                    self.assertEqual(response.status, 200)
                break
            except urllib.error.URLError:
                time.sleep(0.05)
        else:
            proc.kill()
            _out, errors = proc.communicate(timeout=2)
            self.fail(f"isolated viewer did not start: {errors.decode()[:400]}")
        for host in ("attacker.example", f"attacker.example:{port}",
                     f"127.0.0.1:{port + 1}"):
            request = urllib.request.Request(base, headers={"Host": host})
            with self.assertRaises(urllib.error.HTTPError) as denied:
                urllib.request.urlopen(request, timeout=2)
            with denied.exception as response:
                self.assertEqual(response.code, 403)
                self.assertNotIn(b"private", response.read())
        request = urllib.request.Request(base, headers={"Host": f"localhost:{port}"})
        with urllib.request.urlopen(request, timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(json.load(response)["private"], True)

    def test_upgrade_retains_local_pack_index_and_dependencies(self) -> None:
        old = self.bundled()
        target = self.base / "installed"
        pilot.stage(old, target)
        (target / ".data/kg.db").write_bytes(b"client index")
        (target / "node_modules/yaml").mkdir(parents=True)
        (target / "node_modules/yaml/index.js").write_text("installed dependency")
        pack = target / "packs" / pilot.PACK / "roots.yaml"
        before_pack = pack.read_bytes()
        (self.source / "engine/query.mjs").write_text("reviewed version two\n")
        newer = self.base / "new-bundle"
        pilot.bundle(self.source, newer)
        backup = pilot.upgrade(newer, target, port=0)
        self.assertEqual((target / "engine/query.mjs").read_text(), "reviewed version two\n")
        self.assertEqual((backup / "engine/query.mjs").read_text(), "generic fixture\n")
        self.assertEqual((target / ".data/kg.db").read_bytes(), b"client index")
        self.assertEqual((target / "node_modules/yaml/index.js").read_text(), "installed dependency")
        self.assertEqual(pack.read_bytes(), before_pack)
        pilot.verify(target, staged=True)

    def test_upgrade_refuses_drifted_managed_code(self) -> None:
        old = self.bundled()
        target = self.base / "installed"
        pilot.stage(old, target)
        (target / "engine/query.mjs").write_text("local edit")
        with self.assertRaisesRegex(ValueError, "changed"):
            pilot.upgrade(old, target, port=0)
        self.assertEqual((target / "engine/query.mjs").read_text(), "local edit")

    def test_port_check_uses_reuseaddr_after_listener_closes(self) -> None:
        probe = mock.MagicMock()
        probe.__enter__.return_value = probe
        probe.connect_ex.return_value = errno.ECONNREFUSED
        binder = mock.MagicMock()
        binder.__enter__.return_value = binder
        with mock.patch.object(pilot.socket, "socket", side_effect=[probe, binder]):
            pilot.port_free(4180)
        binder.setsockopt.assert_called_once_with(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        binder.bind.assert_called_once_with(("127.0.0.1", 4180))

    def test_port_check_refuses_live_listener(self) -> None:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            with self.assertRaisesRegex(ValueError, "stop the graph viewer"):
                pilot.port_free(port)


if __name__ == "__main__":
    unittest.main()
