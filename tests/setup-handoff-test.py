#!/usr/bin/env python3
"""Isolated setup-text handoff proof. No real Tailscale or iMessage calls."""

import importlib.util
import http.client
import json
import os
import stat
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("wb_setup_handoff", ROOT / "setup.py")
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)

PHONE = "+15551234567"
DNS = "aurora.example-tailnet.ts.net"
PORT = 8790
TOKEN = "b" * 64
PREFIX = f"/p/{TOKEN}"


class SetupHandoffTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="wb-setup-handoff-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        token_dir = self.home / ".wideband" / "fleetdeck"
        token_dir.mkdir(parents=True, mode=0o700)
        token_file = token_dir / "phone-access-token"
        token_file.write_text(TOKEN + "\n", encoding="ascii")
        token_file.chmod(0o600)
        environment = mock.patch.dict(os.environ, {"FLEETDECK_ACCESS_TOKEN_PATH": str(token_file)})
        environment.start()
        self.addCleanup(environment.stop)
        self.store = setup.StateStore(self.home / ".wideband" / "setup")
        (self.home / ".sop-vars").write_text(f"export OPERATOR_PHONE={PHONE}\n", encoding="utf-8")
        portal = self.home / "srv" / "fleetdeck" / "config.json"
        portal.parent.mkdir(parents=True)
        portal.write_text(json.dumps({"ports": {"portal": PORT}}), encoding="utf-8")
        tailscale = self.home / "Applications" / "Tailscale.app" / "Contents" / "MacOS" / "Tailscale"
        tailscale.parent.mkdir(parents=True)
        tailscale.write_text("fake", encoding="utf-8")
        tailscale.chmod(0o755)
        self.runtime = self.home / ".wideband" / "imessage"
        for folder in setup.HANDOFF_OUTBOX_STATES:
            path = self.runtime / "outbox" / folder
            path.mkdir(parents=True, mode=0o700)
        self.runtime.chmod(0o700)
        (self.runtime / "outbox").chmod(0o700)
        setup.write_private(self.runtime / "config.json", json.dumps({
            "owner_phone": PHONE,
            "agent_command": "claude",
            "session": "wb-head",
            "binding": {"chat_id": 7, "chat_guid": "iMessage;-;owner", "account_login": "agent@example.test"},
        }))
        self.store.update(lambda state: state.update({
            "metadata": {
                "os_name": "Aurora", "agent_name": "Trace", "first_goal": "website",
                "agent_provider": "claude",
            },
            "completed": {
                "prove.messaging": {"source": "human", "at": setup.now()},
                "prove.phone-board": {"source": "human", "at": setup.now()},
            },
            "action_runs": {
                "run_imessage_bind": {"status": "complete"},
                "run_first_goal_apply": {"status": "complete"},
                "run_phone_install": {"status": "complete"},
            },
            "last_verification": {
                "generated_at": setup.now(),
                "checks": [
                    {"id": check, "status": "pass"}
                    for check in ("P6-IMSGCHAT", "P6-IMSGHEAD", "P6-IMSGSERVICES")
                ],
            },
        }))
        self.serve = {
            "TCP": {str(PORT): {"HTTPS": True}},
            "Web": {f"{DNS}:{PORT}": {"Handlers": {"/": {"Proxy": f"http://127.0.0.1:{PORT}"}}}},
        }
        self.calls = []
        self.page_calls = []
        self.broken_page = None
        self.api_calls = []
        self.broken_api = None
        setup.confirm_setup_handoff(self.store)

    def run_tailscale(self, command, **_kwargs):
        self.calls.append(command[1:])
        if command[1:] == ["status", "--json"]:
            data = {"Self": {"DNSName": DNS + "."}}
        elif command[1:] == ["serve", "status", "--json"]:
            data = self.serve
        else:
            raise AssertionError(command)
        return subprocess.CompletedProcess(command, 0, json.dumps(data), "")

    @staticmethod
    def probe(_scheme, _host, _port):
        return True

    def surface_probe(self, host, port, path):
        self.page_calls.append((host, port, path))
        return path != self.broken_page

    def api_probe(self, host, port, path):
        self.api_calls.append((host, port, path))
        return path != self.broken_api

    def queue(self):
        return setup.queue_setup_handoff(
            self.store, self.home, runner=self.run_tailscale,
            probe=self.probe, surface_probe=self.surface_probe, api_probe=self.api_probe,
        )

    def files(self):
        return list((self.runtime / "outbox" / "pending").glob("*.txt"))

    def test_verified_handoff_queues_only_private_guarded_files_once(self):
        self.assertEqual(self.queue(), {"status": "queued", "queued": 2})
        self.assertEqual([path.name for path in sorted(self.files())], list(setup.HANDOFF_FILE_NAMES))
        first, second = [path.read_text(encoding="utf-8") for path in sorted(self.files())]
        self.assertIn(f"Dashboard: https://{DNS}:{PORT}{PREFIX}/phone", first)
        for path in ("/agent", "/project", "/graph", "/watch", "/notes"):
            self.assertIn(f"https://{DNS}:{PORT}{PREFIX}{path}", first)
        self.assertIn("Live terminal (read only)", first)
        self.assertIn("Notes (beta)", first)
        self.assertIn("https://apps.apple.com/us/app/tailscale/id1470499037", second)
        self.assertIn("https://apps.apple.com/us/app/termius-modern-ssh-client/id549039908", second)
        self.assertIn(f"Termius SSH host: {DNS}", second)
        self.assertIn("use your Mac login name after enabling Remote Login", second)
        self.assertIn("tmux ls", second)
        self.assertIn("tmux attach -t wb-head", second)
        self.assertIn("claude -c", second)
        self.assertNotIn("tm ls", second)
        for path in self.files():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertLess(len(path.read_text(encoding="utf-8")), 1501)
        self.assertEqual(self.store.read()["handoff"]["version"], 1)
        self.assertEqual(self.store.read()["handoff"]["status"], "queued")
        self.assertEqual([path for _host, _port, path in self.page_calls],
                         [PREFIX + "/phone"] + [PREFIX + path for path in setup.HANDOFF_PAGE_MARKERS])
        self.assertTrue(all(host == DNS and port == PORT for host, port, _path in self.page_calls))
        self.assertEqual([path for _host, _port, path in self.api_calls],
                         [PREFIX + "/api/watch", PREFIX + "/api/notes"])
        (self.runtime / "outbox" / "pending" / setup.HANDOFF_FILE_NAMES[0]).unlink()
        self.assertEqual(self.queue(), {"status": "held", "queued": 0})
        self.assertEqual(len(self.files()), 1)
        self.assertEqual(self.store.read()["handoff"]["status"], "held")
        self.assertEqual(self.calls.count(["status", "--json"]), 2)

    def test_delivery_status_tracks_pending_sent_and_stale_processing_without_retry(self):
        self.assertEqual(setup.handoff_delivery_status(self.home, self.store.read())["status"], "not_queued")
        self.queue()
        delivery = setup.handoff_delivery_status(self.home, self.store.read())
        self.assertEqual((delivery["status"], delivery["sent"], delivery["pending"]), ("pending", 0, 2))
        first, second = setup.HANDOFF_FILE_NAMES
        (self.runtime / "outbox" / "pending" / first).replace(self.runtime / "outbox" / "sent" / first)
        processing = self.runtime / "outbox" / "processing" / second
        (self.runtime / "outbox" / "pending" / second).replace(processing)
        delivery = setup.handoff_delivery_status(self.home, self.store.read())
        self.assertEqual((delivery["status"], delivery["sent"], delivery["pending"], delivery["processing"]),
                         ("pending", 1, 1, 1))
        with mock.patch.object(setup.time, "time", return_value=processing.stat().st_ctime + 91):
            delivery = setup.handoff_delivery_status(self.home, self.store.read())
        self.assertEqual((delivery["status"], delivery["stale_processing"]), ("held", 1))
        processing.replace(self.runtime / "outbox" / "sent" / second)
        delivery = setup.handoff_delivery_status(self.home, self.store.read())
        self.assertEqual((delivery["status"], delivery["sent"], delivery["pending"]), ("sent", 2, 0))

    def test_legacy_loose_or_missing_outbox_is_unqueued_until_repaired(self):
        outbox = self.runtime / "outbox"
        outbox.chmod(0o755)
        before = self.store.path.read_bytes()
        delivery = setup.handoff_delivery_status(self.home, self.store.read())
        self.assertEqual((delivery["status"], delivery["unsafe"], delivery["missing"]),
                         ("not_queued", 0, 0))
        self.assertEqual(self.store.path.read_bytes(), before)
        with self.assertRaisesRegex(RuntimeError, "outbox root is unsafe; repair"):
            self.queue()
        self.assertEqual(self.files(), [])
        outbox.chmod(0o700)
        (outbox / "review").rmdir()
        self.assertEqual(setup.handoff_delivery_status(self.home, self.store.read())["status"], "not_queued")
        (outbox / "review").mkdir(mode=0o700)
        self.queue()
        outbox.chmod(0o755)
        delivery = setup.handoff_delivery_status(self.home, self.store.read())
        self.assertEqual((delivery["status"], delivery["unsafe"]), ("held", 2))

    def test_delivery_status_marks_review_rejection_missing_and_symlinks(self):
        self.queue()
        first, second = setup.HANDOFF_FILE_NAMES
        first_path = self.runtime / "outbox" / "pending" / first
        second_path = self.runtime / "outbox" / "pending" / second
        review = self.runtime / "outbox" / "review" / first
        rejected = self.runtime / "outbox" / "rejected" / first
        first_path.replace(review)
        delivery = setup.handoff_delivery_status(self.home, self.store.read())
        self.assertEqual((delivery["status"], delivery["review"]), ("held", 1))
        review.replace(rejected)
        delivery = setup.handoff_delivery_status(self.home, self.store.read())
        self.assertEqual((delivery["status"], delivery["rejected"]), ("rejected", 1))
        rejected.unlink()
        delivery = setup.handoff_delivery_status(self.home, self.store.read())
        self.assertEqual((delivery["status"], delivery["missing"]), ("missing", 1))
        first_path.symlink_to(self.home / "missing-target")
        delivery = setup.handoff_delivery_status(self.home, self.store.read())
        self.assertEqual((delivery["status"], delivery["unsafe"]), ("held", 1))
        first_path.unlink()
        (self.runtime / "outbox" / "sent" / second).write_text("duplicate", encoding="utf-8")
        delivery = setup.handoff_delivery_status(self.home, self.store.read())
        self.assertEqual((delivery["status"], delivery["unsafe"]), ("held", 1))
        self.assertEqual(delivery["pending"], 0)
        alias = self.home / "alias"
        alias.mkdir()
        (alias / ".wideband").symlink_to(self.home / ".wideband", target_is_directory=True)
        delivery = setup.handoff_delivery_status(alias, self.store.read())
        self.assertEqual((delivery["status"], delivery["unsafe"]), ("held", 2))

    def test_authenticated_state_reconciles_delivery_without_persisting_or_sending(self):
        self.queue()
        first = setup.HANDOFF_FILE_NAMES[0]
        (self.runtime / "outbox" / "pending" / first).replace(
            self.runtime / "outbox" / "review" / first
        )
        app = setup.SetupApp(self.store)
        setup.Handler.app = app
        server = setup.LoopbackHTTPServer(("127.0.0.1", 0), setup.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        before = self.store.path.read_bytes()
        try:
            with mock.patch.object(setup.Path, "home", return_value=self.home):
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                try:
                    connection.request("GET", "/api/state", headers={"X-Wideband-Token": app.token})
                    response = connection.getresponse()
                    payload = json.loads(response.read())
                finally:
                    connection.close()
            self.assertEqual(response.status, 200)
            self.assertEqual(payload["state"]["handoff"]["delivery"]["status"], "held")
            self.assertEqual(payload["state"]["handoff"]["delivery"]["review"], 1)
            self.assertEqual(self.store.path.read_bytes(), before)
            self.assertEqual(self.store.read()["handoff"]["status"], "queued")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_partial_queue_resumes_without_repeating_first_text(self):
        sent = self.runtime / "outbox" / "sent" / setup.HANDOFF_FILE_NAMES[0]
        sent.write_text("previous handoff", encoding="utf-8")
        self.assertEqual(self.queue(), {"status": "queued", "queued": 1})
        self.assertEqual(sent.read_text(encoding="utf-8"), "previous handoff")
        self.assertEqual([path.name for path in self.files()], [setup.HANDOFF_FILE_NAMES[1]])

    def test_missing_proofs_or_wrong_binding_never_queue(self):
        for change in (
            lambda state: state["completed"].pop("prove.messaging"),
            lambda state: state["completed"].pop("prove.phone-board"),
            lambda state: state["action_runs"]["run_first_goal_apply"].update({"status": "needs_attention"}),
            lambda state: state["last_verification"]["checks"][0].update({"status": "fail"}),
            lambda state: state["metadata"].update({"agent_provider": "codex"}),
            lambda state: state["lifecycle"].update({"deactivated_at": setup.now()}),
        ):
            original = self.store.read()
            self.store.update(change)
            with self.assertRaises((ValueError, RuntimeError)):
                self.queue()
            self.assertEqual(self.files(), [])
            self.store.update(lambda state: state.clear() or state.update(original))
        config = json.loads((self.runtime / "config.json").read_text(encoding="utf-8"))
        config["owner_phone"] = "+1" + "555" + "7654321"
        setup.write_private(self.runtime / "config.json", json.dumps(config))
        with self.assertRaisesRegex(RuntimeError, "binding does not match"):
            self.queue()
        self.assertEqual(self.files(), [])

    def test_explicit_approval_is_required_even_for_completed_setup(self):
        self.store.update(lambda state: state["handoff"].clear())
        with self.assertRaisesRegex(RuntimeError, "approve the setup texts"):
            self.queue()
        self.assertEqual(self.files(), [])
        self.assertEqual(setup.confirm_setup_handoff(self.store)["status"], "approved")
        self.assertEqual(self.queue(), {"status": "queued", "queued": 2})

    def test_confirmation_endpoint_needs_private_token_and_direct_approval(self):
        self.store.update(lambda state: state["handoff"].clear())
        app = setup.SetupApp(self.store)
        setup.Handler.app = app
        server = setup.LoopbackHTTPServer(("127.0.0.1", 0), setup.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def post(token, payload):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            try:
                connection.request("POST", "/api/handoff/confirm", json.dumps(payload), headers={
                    "Content-Type": "application/json", "X-Wideband-Token": token,
                })
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally:
                connection.close()

        try:
            self.assertEqual(post("wrong", {"confirm": True})[0], 401)
            self.assertEqual(post(app.token, {"confirm": False})[0], 400)
            self.assertNotIn("approved_at", self.store.read()["handoff"])
            status, response = post(app.token, {"confirm": True})
            self.assertEqual(status, 200)
            self.assertEqual(response["status"], "approved")
            self.assertEqual(response["approved_at"], self.store.read()["handoff"]["approved_at"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_review_or_rejected_text_is_held_without_receipt_or_retry(self):
        review = self.runtime / "outbox" / "review" / setup.HANDOFF_FILE_NAMES[0]
        review.write_text("uncertain delivery", encoding="utf-8")
        self.assertEqual(self.queue(), {"status": "held", "queued": 0})
        self.assertEqual(self.files(), [])
        record = self.store.read()["handoff"]
        self.assertEqual(record["status"], "held")
        self.assertNotIn("version", record)
        review.unlink()
        self.assertEqual(self.queue(), {"status": "held", "queued": 0})
        self.assertEqual(self.files(), [])
        sent = self.runtime / "outbox" / "sent" / setup.HANDOFF_FILE_NAMES[0]
        sent.write_text("operator confirmed prior delivery", encoding="utf-8")
        self.assertEqual(self.queue(), {"status": "queued", "queued": 1})
        self.assertEqual([path.name for path in self.files()], [setup.HANDOFF_FILE_NAMES[1]])

    def test_review_after_queue_supersedes_queued_status(self):
        self.queue()
        source = self.runtime / "outbox" / "pending" / setup.HANDOFF_FILE_NAMES[0]
        target = self.runtime / "outbox" / "rejected" / setup.HANDOFF_FILE_NAMES[0]
        source.replace(target)
        self.assertEqual(self.queue(), {"status": "held", "queued": 0})
        self.assertEqual(self.store.read()["handoff"]["status"], "held")
        self.assertEqual(self.queue(), {"status": "held", "queued": 0})

    def test_symlinked_handoff_file_is_held(self):
        target = self.home / "unrelated.txt"
        target.write_text("not a setup message", encoding="utf-8")
        (self.runtime / "outbox" / "pending" / setup.HANDOFF_FILE_NAMES[0]).symlink_to(target)
        self.assertEqual(self.queue(), {"status": "held", "queued": 0})
        self.assertEqual(self.store.read()["handoff"]["status"], "held")
        self.assertEqual(len(self.files()), 1)

    def test_unverified_or_public_phone_route_never_queue(self):
        self.serve["AllowFunnel"] = {f"{DNS}:{PORT}": True}
        with self.assertRaisesRegex(RuntimeError, "private Fleetdeck HTTPS"):
            self.queue()
        self.assertEqual(self.files(), [])
        self.serve.pop("AllowFunnel")
        self.serve["Web"][f"{DNS}:{PORT}"]["Handlers"]["/"]["Proxy"] = "http://127.0.0.1:9999"
        with self.assertRaisesRegex(RuntimeError, "private Fleetdeck HTTPS"):
            self.queue()
        self.assertEqual(self.files(), [])

    def test_every_customer_route_must_answer_over_private_https(self):
        for path in setup.HANDOFF_PAGE_MARKERS:
            self.broken_page = PREFIX + path
            self.page_calls.clear()
            expected_error = "private Fleetdeck HTTPS" if path == "/phone" else "every Fleetdeck phone page"
            with self.assertRaisesRegex(RuntimeError, expected_error):
                self.queue()
            self.assertEqual(self.files(), [])
            self.assertIn((DNS, PORT, PREFIX + path), self.page_calls)
        self.broken_page = None
        for path in ("/api/watch", "/api/notes"):
            self.broken_api = PREFIX + path
            self.api_calls.clear()
            with self.assertRaisesRegex(RuntimeError, "read endpoints"):
                self.queue()
            self.assertEqual(self.files(), [])
            self.assertIn((DNS, PORT, PREFIX + path), self.api_calls)

    def test_page_probe_rejects_redirects_wrong_html_and_missing_markers(self):
        pages = {PREFIX + path: "<html>" + " ".join(markers) + "</html>"
                 for path, markers in setup.HANDOFF_PAGE_MARKERS.items()}

        class Response:
            def __init__(self, page, status=200, mime="text/html; charset=utf-8"):
                self.status, self.page, self.mime = status, page.encode(), mime

            def getheader(self, name):
                return self.mime if name == "Content-Type" else None

            def read(self, amount):
                return self.page[:amount]

        class Connection:
            def __init__(self, host, port, **_kwargs):
                self.assert_host = (host, port)
                self.path = None

            def request(self, method, path, **_kwargs):
                if method != "GET":
                    raise AssertionError(method)
                self.path = path

            def getresponse(self):
                return responses[self.path]

            def close(self):
                pass

        responses = {path: Response(page) for path, page in pages.items()}
        responses[PREFIX + "/api/watch"] = Response(json.dumps({"running": True, "text": "ready"}), mime="application/json")
        responses[PREFIX + "/api/notes"] = Response(json.dumps({"notes": []}), mime="application/json")
        with mock.patch.object(setup.http.client, "HTTPSConnection", Connection):
            for path in pages:
                self.assertTrue(setup.portal_handoff_page(DNS, PORT, path), path)
            for path in (PREFIX + "/api/watch", PREFIX + "/api/notes"):
                self.assertTrue(setup.portal_handoff_api(DNS, PORT, path), path)
            responses[PREFIX + "/project"] = Response(pages[PREFIX + "/project"], status=302)
            self.assertFalse(setup.portal_handoff_page(DNS, PORT, PREFIX + "/project"))
            for status in (403, 404):
                responses[PREFIX + "/phone"] = Response(pages[PREFIX + "/phone"], status=status)
                self.assertFalse(setup.portal_handoff_page(DNS, PORT, PREFIX + "/phone"))
            responses[PREFIX + "/project"] = Response(pages[PREFIX + "/project"], mime="text/plain")
            self.assertFalse(setup.portal_handoff_page(DNS, PORT, PREFIX + "/project"))
            responses[PREFIX + "/project"] = Response("<html>generic page</html>")
            self.assertFalse(setup.portal_handoff_page(DNS, PORT, PREFIX + "/project"))
            responses[PREFIX + "/api/notes"] = Response(json.dumps({"notes": []}), status=503, mime="application/json")
            self.assertFalse(setup.portal_handoff_api(DNS, PORT, PREFIX + "/api/notes"))
            responses[PREFIX + "/api/watch"] = Response(json.dumps({"running": "yes"}), mime="application/json")
            self.assertFalse(setup.portal_handoff_api(DNS, PORT, PREFIX + "/api/watch"))
            responses[PREFIX + "/api/watch"] = Response(json.dumps({"running": False, "text": ""}), mime="application/json")
            self.assertFalse(setup.portal_handoff_api(DNS, PORT, PREFIX + "/api/watch"))
            self.assertFalse(setup.portal_handoff_page(DNS, PORT, "/phone"))
            self.assertFalse(setup.portal_handoff_api(DNS, PORT, "/api/notes"))
            self.assertFalse(setup.portal_handoff_page(DNS, PORT, "/p/" + "A" * 64 + "/phone"))

    def test_handoff_rejects_links_without_exact_phone_capability(self):
        for path in ("/phone", PREFIX + "/board", PREFIX + "/phone/", "/p/" + "A" * 64 + "/phone"):
            with self.assertRaisesRegex(RuntimeError, "valid private phone link"):
                setup._handoff_messages(f"https://{DNS}:{PORT}{path}", "Trace", "Aurora", False)

    def test_tm_shortcut_only_when_installed(self):
        tm = self.home / "bin" / "tm"
        tm.parent.mkdir()
        tm.write_text("fake", encoding="utf-8")
        tm.chmod(0o755)
        self.queue()
        second = (self.runtime / "outbox" / "pending" / setup.HANDOFF_FILE_NAMES[1]).read_text()
        self.assertIn("tm ls", second)


if __name__ == "__main__":
    unittest.main()
