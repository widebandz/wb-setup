#!/usr/bin/env python3
"""Isolated transport contract tests. No test invokes the real imsg binary."""

import datetime as dt
import hashlib
import importlib.util
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("wb_imessage_runtime", ROOT / "imessage" / "runtime.py")
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)

OWNER = "+15551234567"
OTHER = "+1" + "555" + "7654321"
FORGED = "+1" + "555" + "0000000"
AGENT_ACCOUNT = "head@example.test"
CHAT = {
    "id": 7, "guid": "iMessage;-;+15551234567", "service": "iMessage",
    "is_group": False, "participants": [OWNER], "account_login": AGENT_ACCOUNT,
}


def completed(args, stdout="", code=0):
    return subprocess.CompletedProcess(args, code, stdout, "")


class FakeCommands:
    def __init__(self):
        self.chat = dict(CHAT)
        self.pane_command = "zsh"
        self.calls = []
        self.send_result = '{"status":"sent"}\n'
        self.record_prompt = True
        self.last_prompt = None
        self.transcript = None
        self.workspace = None

    def __call__(self, args, **_kwargs):
        self.calls.append(args)
        if Path(args[0]).name == "tmux":
            if args[1] == "list-panes":
                return completed(args, f"1|1|%42|{self.pane_command}\n")
            if args[1] == "send-keys":
                if "-l" in args:
                    self.last_prompt = args[-1]
                elif args[-1] == "Enter" and self.record_prompt and self.transcript:
                    with self.transcript.open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps({
                            "type": "user", "cwd": self.workspace,
                            "sessionId": self.transcript.stem,
                            "message": {"role": "user", "content": self.last_prompt},
                        }) + "\n")
            return completed(args)
        if args[1] == "chats":
            return completed(args, json.dumps({"id": self.chat["id"]}) + "\n")
        if args[1] == "group":
            return completed(args, json.dumps(self.chat) + "\n")
        if args[1] == "history":
            first = {
                "id": 81, "guid": "message-81", "chat_id": self.chat["id"],
                "chat_guid": self.chat["guid"], "sender": OWNER,
                "is_from_me": False, "text": "Hello head",
                "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
            return completed(args, json.dumps(first) + "\n")
        if args[1] == "send":
            return completed(args, self.send_result)
        raise AssertionError(args)


class ImsgRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="wb-imessage-test-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.fake = FakeCommands()
        self.rt = runtime.Runtime(self.home, runner=self.fake)
        for name in ("inbox/pending", "inbox/processing", "inbox/delivered",
                     "outbox/pending", "outbox/processing", "outbox/sent",
                     "outbox/rejected", "outbox/review"):
            runtime.private_dir(self.rt.state / name)
        self.cfg = {
            "schema_version": 1, "owner_phone": OWNER, "os_name": "Aster",
            "agent_name": "Iris", "agent_command": "claude", "session": "wb-head",
            "workspace": str(self.home / "wideband" / "head"),
            "imsg_path": str(self.home / "fake-imsg"), "binding": None,
        }
        (self.home / "fake-imsg").write_text("fake", encoding="utf-8")
        runtime.atomic_json(self.rt.config_path, self.cfg)
        project = runtime.re.sub(r"[^A-Za-z0-9-]", "-", self.cfg["workspace"])
        transcript_dir = self.home / ".claude" / "projects" / project
        transcript_dir.mkdir(parents=True)
        self.fake.transcript = transcript_dir / "00000000-0000-4000-8000-000000000001.jsonl"
        self.fake.transcript.write_text('{"type":"system"}\n', encoding="utf-8")
        self.fake.workspace = self.cfg["workspace"]
        for name, value in (("HEAD_STABLE_SECONDS", 0), ("CLAUDE_ACK_SECONDS", 0)):
            patcher = mock.patch.object(runtime, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def bind(self):
        with mock.patch.object(runtime.platform, "system", return_value="Darwin"), \
             mock.patch.object(runtime.platform, "mac_ver", return_value=("15.0", (), "")):
            return self.rt.bind(expected_account=AGENT_ACCOUNT)

    def test_bind_requires_one_exact_owner_chat_and_fresh_inbound(self):
        self.fake.chat["is_group"] = True
        with self.assertRaisesRegex(ValueError, "found 0"):
            self.bind()
        self.fake.chat["is_group"] = False
        self.fake.chat["participants"] = [OWNER, OTHER]
        with self.assertRaisesRegex(ValueError, "found 0"):
            self.bind()
        self.fake.chat["participants"] = [OWNER]
        with self.assertRaisesRegex(ValueError, "found 0"):
            with mock.patch.object(runtime.platform, "system", return_value="Darwin"), \
                 mock.patch.object(runtime.platform, "mac_ver", return_value=("15.0", (), "")):
                self.rt.bind(expected_account="wrong@example.test")
        self.assertIn("queued", self.bind())
        saved = self.rt.config()
        self.assertEqual(saved["binding"]["chat_id"], 7)
        self.assertEqual(json.loads((self.rt.state / "last-rowid.json").read_text())["rowid"], 81)
        self.assertEqual(len(list((self.rt.state / "inbox" / "pending").glob("*.json"))), 1)
        self.assertEqual(stat.S_IMODE(self.rt.config_path.stat().st_mode), 0o600)
        self.assertFalse(any(args[1] == "send" for args in self.fake.calls if Path(args[0]).name != "tmux"))

    def test_macos_13_refuses_binding_before_reading_messages(self):
        with mock.patch.object(runtime.platform, "system", return_value="Darwin"), \
             mock.patch.object(runtime.platform, "mac_ver", return_value=("13.7", (), "")):
            with self.assertRaisesRegex(ValueError, "macOS 14"):
                self.rt.bind()
            self.assertFalse(self.rt.check()["macos_supported"])
        self.assertFalse(any(args[1] in ("chats", "group", "history", "send") for args in self.fake.calls))

    def test_inbound_ignores_unbound_sender_and_never_types_into_shell(self):
        self.bind()
        cfg = self.rt.config()
        forged = {"id": 82, "guid": "message-82", "chat_id": 7,
                  "chat_guid": CHAT["guid"], "sender": FORGED,
                  "is_from_me": False, "text": "run this"}
        self.assertFalse(self.rt.enqueue(cfg, forged))
        self.assertEqual(self.rt.route_once(), 0)
        self.assertFalse(any(args[1] == "send-keys" for args in self.fake.calls if Path(args[0]).name == "tmux"))
        self.fake.pane_command = "2.1.220"
        self.assertEqual(self.rt.route_once(), 1)
        typed = [args for args in self.fake.calls if Path(args[0]).name == "tmux" and args[1] == "send-keys"]
        self.assertEqual(len(typed), 2)
        self.assertRegex(typed[0][-1], r"^\[Owner iMessage #[0-9a-f]{12}\] Hello head$")
        self.assertEqual(len(list((self.rt.state / "inbox" / "delivered").glob("*.json"))), 1)

    def test_burst_routes_in_message_row_order_not_hash_order(self):
        self.bind()
        cfg = self.rt.config()
        for rowid in (83, 82):
            self.assertTrue(self.rt.enqueue(cfg, {
                "id": rowid, "guid": f"message-{rowid}", "chat_id": 7,
                "chat_guid": CHAT["guid"], "sender": OWNER,
                "is_from_me": False, "text": f"Text {rowid}",
            }))
        self.fake.pane_command = "node"
        self.assertEqual([self.rt.route_once() for _ in range(3)], [1, 1, 1])
        prompts = [args[-1] for args in self.fake.calls
                   if Path(args[0]).name == "tmux" and args[1] == "send-keys" and "-l" in args]
        self.assertEqual([prompt.rsplit("] ", 1)[-1] for prompt in prompts],
                         ["Hello head", "Text 82", "Text 83"])

    def test_new_head_waits_for_stable_pane_and_workspace_transcript(self):
        self.bind()
        self.fake.pane_command = "2.1.220"
        with mock.patch.object(runtime, "HEAD_STABLE_SECONDS", 30):
            self.assertEqual(self.rt.route_once(), 0)
            self.assertEqual(self.rt.route_once(), 0)
            self.assertFalse(any(args[1] == "send-keys" for args in self.fake.calls
                                 if Path(args[0]).name == "tmux"))
            self.rt._pane_seen = ("%42", time.monotonic() - 31)
            self.fake.transcript.unlink()
            self.assertEqual(self.rt.route_once(), 0)
            self.fake.transcript.write_text('{"type":"system"}\n', encoding="utf-8")
            self.assertEqual(self.rt.route_once(), 1)

    def test_no_claude_acceptance_holds_message_for_review_without_replay(self):
        self.bind()
        self.assertTrue(self.rt.enqueue(self.rt.config(), {
            "id": 82, "guid": "message-82", "chat_id": 7,
            "chat_guid": CHAT["guid"], "sender": OWNER,
            "is_from_me": False, "text": "A second request",
        }))
        self.fake.pane_command = "2.1.220"
        self.fake.record_prompt = False
        old_prompt = "[Owner iMessage #" + hashlib.sha256(b"message-81").hexdigest()[:12] + "] Hello head"
        with self.fake.transcript.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({
                "type": "user", "cwd": self.cfg["workspace"],
                "sessionId": self.fake.transcript.stem,
                "message": {"role": "user", "content": old_prompt},
            }) + "\n")
        with self.assertRaisesRegex(ValueError, "held for review"):
            self.rt.route_once()
        self.assertEqual(self.rt.check()["inbox_review_count"], 1)
        self.assertEqual(len(list((self.rt.state / "inbox" / "delivered").glob("*.json"))), 0)
        typed = [args for args in self.fake.calls
                 if Path(args[0]).name == "tmux" and args[1] == "send-keys"]
        self.assertEqual(len(typed), 2)
        self.assertEqual(self.rt.route_once(), 0)
        self.assertEqual(len(list((self.rt.state / "inbox" / "pending").glob("*.json"))), 1)
        self.assertEqual(len([args for args in self.fake.calls
                              if Path(args[0]).name == "tmux" and args[1] == "send-keys"]), 2)

    def test_other_workspace_user_row_cannot_acknowledge_delivery(self):
        self.bind()
        self.fake.pane_command = "2.1.220"
        self.fake.workspace = str(self.home / "another-project")
        with self.assertRaisesRegex(ValueError, "held for review"):
            self.rt.route_once()
        self.assertEqual(self.rt.check()["inbox_review_count"], 1)

    def test_outbox_validates_target_and_holds_uncertain_send(self):
        self.bind()
        pending = self.rt.state / "outbox" / "pending"
        (pending / "reply.txt").write_text("Hello from Iris", encoding="utf-8")
        self.assertEqual(self.rt.outbox_once(), 1)
        send_calls = [args for args in self.fake.calls if len(args) > 1 and args[1] == "send"]
        self.assertEqual(len(send_calls), 1)
        self.assertEqual(send_calls[0][send_calls[0].index("--chat-id") + 1], "7")
        self.assertTrue((self.rt.state / "outbox" / "sent" / "reply.txt").exists())

        (pending / "next.txt").write_text("Hold this", encoding="utf-8")
        self.fake.chat["guid"] = "new-target"
        with self.assertRaisesRegex(ValueError, "held for review"):
            self.rt.outbox_once()
        self.assertEqual(len([args for args in self.fake.calls if len(args) > 1 and args[1] == "send"]), 1)
        self.assertTrue((self.rt.state / "outbox" / "review" / "next.txt").exists())

    def test_ambiguous_send_is_held_without_retry(self):
        self.bind()
        pending = self.rt.state / "outbox" / "pending"
        (pending / "reply.txt").write_text("Possible delivery", encoding="utf-8")
        self.fake.send_result = '{"status":"unknown"}\n'
        with self.assertRaisesRegex(ValueError, "held for review"):
            self.rt.outbox_once()
        self.assertTrue((self.rt.state / "outbox" / "review" / "reply.txt").exists())
        self.assertEqual(self.rt.outbox_once(), 0)
        self.assertEqual(len([args for args in self.fake.calls if len(args) > 1 and args[1] == "send"]), 1)

    def test_outbox_rejects_symlink_and_oversize_without_reading_target(self):
        self.bind()
        pending = self.rt.state / "outbox" / "pending"
        secret = self.home / "secret.txt"
        secret.write_text("PRIVATE", encoding="utf-8")
        (pending / "leak.txt").symlink_to(secret)
        (pending / "long.txt").write_text("x" * (runtime.MAX_REPLY + 1), encoding="utf-8")
        self.assertEqual(self.rt.outbox_once(), 0)
        self.assertTrue((self.rt.state / "outbox" / "rejected" / "leak.txt").is_symlink())
        self.assertTrue((self.rt.state / "outbox" / "rejected" / "long.txt").exists())
        self.assertFalse(any(args[1] == "send" for args in self.fake.calls if Path(args[0]).name != "tmux"))

    def test_init_preserves_existing_identity_and_requires_transport(self):
        self.rt.config_path.unlink()
        with mock.patch.object(runtime.shutil, "which", return_value=None):
            with self.assertRaisesRegex(ValueError, "not installed"):
                self.rt.init({"owner_phone": OWNER})
        with mock.patch.object(runtime.shutil, "which", return_value=str(self.home / "fake-imsg")):
            self.rt.init({"owner_phone": OWNER, "os_name": "Aster", "agent_name": "Iris"})
            self.assertEqual(self.rt.init({"owner_phone": OWNER}), "existing private runtime preserved")
            with self.assertRaisesRegex(ValueError, "another head-agent provider"):
                self.rt.init({"owner_phone": OWNER, "agent_command": "codex"})
            with self.assertRaisesRegex(ValueError, "another owner"):
                self.rt.init({"owner_phone": FORGED})
        self.assertTrue((self.home / "wideband" / "head" / "outbox").is_symlink())

    def test_init_and_migration_keep_queue_roots_private(self):
        self.rt.config_path.unlink()
        for root in ("inbox", "outbox"):
            shutil.rmtree(self.rt.state / root)

        with mock.patch.object(runtime.shutil, "which", return_value=str(self.home / "fake-imsg")):
            old_umask = os.umask(0o022)
            try:
                self.rt.init({"owner_phone": OWNER, "os_name": "Aster", "agent_name": "Iris"})
            finally:
                os.umask(old_umask)

            for root in ("inbox", "outbox"):
                self.assertEqual(stat.S_IMODE((self.rt.state / root).stat().st_mode), 0o700)

            inbox_record = self.rt.state / "inbox" / "pending" / "keep.json"
            outbox_reply = self.rt.state / "outbox" / "pending" / "keep.txt"
            runtime.atomic_json(inbox_record, {"text": "queued"})
            outbox_reply.write_text("queued reply", encoding="utf-8")
            outbox_reply.chmod(0o600)
            for root in ("inbox", "outbox"):
                (self.rt.state / root).chmod(0o755)

            self.assertEqual(
                self.rt.init({"owner_phone": OWNER}), "existing private runtime preserved"
            )

        for root in ("inbox", "outbox"):
            self.assertEqual(stat.S_IMODE((self.rt.state / root).stat().st_mode), 0o700)
        self.assertEqual(json.loads(inbox_record.read_text()), {"text": "queued"})
        self.assertEqual(outbox_reply.read_text(), "queued reply")

    def test_init_rejects_redirected_runtime_roots_without_changing_targets(self):
        for root in ("state", "inbox", "outbox"):
            with self.subTest(root=root), tempfile.TemporaryDirectory() as temp:
                home = Path(temp)
                rt = runtime.Runtime(home, runner=FakeCommands())
                target = home / "outside"
                target.mkdir(mode=0o755)
                target.chmod(0o755)
                rt.state.parent.mkdir()
                if root == "state":
                    linked = rt.state
                else:
                    rt.state.mkdir()
                    linked = rt.state / root
                linked.symlink_to(target, target_is_directory=True)

                with mock.patch.object(runtime.shutil, "which", return_value=str(home / "fake-imsg")):
                    with self.assertRaisesRegex(ValueError, "real directory"):
                        rt.init({"owner_phone": OWNER})

                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o755)
                self.assertFalse(rt.config_path.exists())

        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            rt = runtime.Runtime(home, runner=FakeCommands())
            rt.state.mkdir(parents=True)
            blocked = rt.state / "outbox"
            blocked.write_text("existing file", encoding="utf-8")
            with mock.patch.object(runtime.shutil, "which", return_value=str(home / "fake-imsg")):
                with self.assertRaisesRegex(ValueError, "real directory"):
                    rt.init({"owner_phone": OWNER})
            self.assertEqual(blocked.read_text(), "existing file")

    def test_same_owner_rename_preserves_binding_and_client_edits(self):
        self.rt.config_path.unlink()
        with mock.patch.object(runtime.shutil, "which", return_value=str(self.home / "fake-imsg")):
            self.rt.init({"owner_phone": OWNER, "os_name": "Aster", "agent_name": "Iris"})
            workspace = Path(self.rt.config()["workspace"])
            (workspace / "CLAUDE.md").write_text("Client instructions\n", encoding="utf-8")
            before = self.rt.config()
            before["binding"] = {"chat_id": 7, "chat_guid": CHAT["guid"],
                                 "account_login": AGENT_ACCOUNT}
            runtime.atomic_json(self.rt.config_path, before)
            self.fake.pane_command = "2.1.220"
            self.assertIn("next start", self.rt.init({
                "owner_phone": OWNER, "os_name": "Nova", "agent_name": "Kite",
            }))
        after = self.rt.config()
        self.assertEqual(after["binding"], before["binding"])
        self.assertEqual((after["os_name"], after["agent_name"]), ("Nova", "Kite"))
        self.assertTrue(after["names_pending_restart"])
        self.assertTrue((workspace / "AGENTS.md").read_text().startswith("# Kite · Nova"))
        self.assertEqual((workspace / "CLAUDE.md").read_text(), "Client instructions\n")

    def test_architecture_tracks_private_first_goal_without_replacing_client_edits(self):
        self.rt.config_path.unlink()
        setup_state = self.home / ".wideband" / "setup" / "state.json"
        runtime.atomic_json(setup_state, {"metadata": {"first_goal": "research"}})
        with mock.patch.object(runtime.shutil, "which", return_value=str(self.home / "fake-imsg")):
            self.rt.init({"owner_phone": OWNER, "os_name": "Aster", "agent_name": "Iris"})
            workspace = Path(self.rt.config()["workspace"])
            architecture = workspace / "ARCHITECTURE.md"
            starter = architecture.read_text(encoding="utf-8")
            for layer in ("Transport and listener", "Exact owner router",
                          "Persistent head agent", "Guarded outbox", "Research"):
                self.assertIn(layer, starter)
            self.assertIn("first layered design", (workspace / "AGENTS.md").read_text())
            self.assertIn("Collaborate with the owner", (workspace / "CLAUDE.md").read_text())
            self.assertEqual(self.rt.config()["first_goal"], "research")

            runtime.atomic_json(setup_state, {"metadata": {"first_goal": "website"}})
            self.rt.init({"owner_phone": OWNER, "os_name": "Aster", "agent_name": "Iris"})
            self.assertIn("Build a website", architecture.read_text(encoding="utf-8"))
            architecture.write_text("Owner's layered architecture\n", encoding="utf-8")
            (workspace / "CLAUDE.md").write_text("Owner's agent instructions\n", encoding="utf-8")
            runtime.atomic_json(setup_state, {"metadata": {"first_goal": "proposal"}})
            self.rt.init({"owner_phone": OWNER, "os_name": "Nova", "agent_name": "Kite"})

        self.assertEqual(architecture.read_text(encoding="utf-8"), "Owner's layered architecture\n")
        self.assertEqual((workspace / "CLAUDE.md").read_text(), "Owner's agent instructions\n")
        self.assertTrue((workspace / "AGENTS.md").read_text().startswith("# Kite · Nova"))
        self.assertEqual(self.rt.config()["first_goal"], "proposal")

    def test_legacy_generated_instructions_migrate_without_touching_custom_file(self):
        self.rt.config_path.unlink()
        with mock.patch.object(runtime.shutil, "which", return_value=str(self.home / "fake-imsg")):
            self.rt.init({"owner_phone": OWNER, "os_name": "Aster", "agent_name": "Iris"})
            workspace = Path(self.rt.config()["workspace"])
            (workspace / "AGENTS.md").write_text(
                self.rt.legacy_instructions("Iris", "Aster", workspace / "outbox"), encoding="utf-8",
            )
            (workspace / "CLAUDE.md").write_text("Client-owned\n", encoding="utf-8")
            self.rt.init({"owner_phone": OWNER, "os_name": "Aster", "agent_name": "Iris"})
        self.assertIn("ARCHITECTURE.md", (workspace / "AGENTS.md").read_text())
        self.assertEqual((workspace / "CLAUDE.md").read_text(), "Client-owned\n")


class InstallStagingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="wb-imessage-install-test-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.la = self.home / "Library" / "LaunchAgents"
        self.la.mkdir(parents=True)
        (self.home / ".sop-vars").write_text(
            "export ORG=example\nexport BRAND=Wideband\n"
            "export OPERATOR_PHONE=+15551234567\n", encoding="utf-8",
        )
        agent = self.home / "Applications" / "Wideband Agent.app" / "Contents" / "MacOS" / "Wideband Agent"
        agent.parent.mkdir(parents=True)
        agent.write_text("#!/bin/sh\necho '{\"bound\":false}'\n", encoding="utf-8")
        agent.chmod(0o755)
        toolchain = self.home / ".wideband" / "toolchain"
        version = toolchain / "versions" / "install-staging-test"
        self.bin = version / "bin"
        self.bin.mkdir(parents=True, mode=0o700)
        for directory in (self.home / ".wideband", toolchain,
                          toolchain / "versions", version, self.bin):
            directory.chmod(0o700)
        active = toolchain / "active"
        active.write_text("install-staging-test\n", encoding="ascii")
        active.chmod(0o600)
        self.loaded = self.home / "loaded"
        self.loaded.mkdir()
        self.log = self.home / "launchctl.log"
        launchctl = self.bin / "launchctl"
        launchctl.write_text(
            "#!/bin/sh\n"
            "printf '%s %s\\n' \"$1\" \"$2\" >> \"$WB_TEST_LAUNCH_LOG\"\n"
            "label=${2##*/}\n"
            "case \"$1\" in\n"
            "  print) test -f \"$WB_TEST_LOADED/$label\" ;;\n"
            "  bootout) rm -f \"$WB_TEST_LOADED/$label\" ;;\n"
            "  bootstrap) label=${3##*/}; touch \"$WB_TEST_LOADED/${label%.plist}\" ;;\n"
            "  *) exit 99 ;;\n"
            "esac\n", encoding="utf-8",
        )
        launchctl.chmod(0o755)
        for name, body in (("sw_vers", "echo 15.0\n"), ("tmux", "exit 0\n"),
                           ("imsg", "exit 0\n"),
                           ("python3", f"exec {shlex.quote(sys.executable)} \"$@\"\n")):
            script = self.bin / name
            script.write_text("#!/bin/sh\n" + body, encoding="utf-8")
            script.chmod(0o700)
        launchctl.chmod(0o700)
        manifest = version / "manifest.sha256"
        manifest.write_text("".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  bin/{path.name}\n"
            for path in sorted(self.bin.iterdir())
        ), encoding="ascii")
        manifest.chmod(0o600)
        self.env = dict(os.environ, HOME=str(self.home),
                        PATH=str(self.bin) + ":" + os.environ.get("PATH", ""),
                        WB_TEST_LAUNCH_LOG=str(self.log), WB_TEST_LOADED=str(self.loaded))

    def test_unbound_install_disables_only_exact_jobs_and_survives_rerun(self):
        jobs = ("watch", "route", "keep", "outbox")
        for job in jobs:
            label = f"com.example.imessage-{job}"
            (self.la / f"{label}.plist").write_text("old active plist\n", encoding="utf-8")
            (self.loaded / label).write_text("loaded\n", encoding="utf-8")
        unrelated = self.la / "com.other.healthcheck.plist"
        unrelated.write_text("operator plist\n", encoding="utf-8")

        before = subprocess.run(
            ["bash", str(ROOT / "verify.sh"), "--imessage-only", "--json"],
            env=self.env, capture_output=True, text=True, timeout=20, check=False,
        )
        checks = {check["id"]: check for check in json.loads(before.stdout)["checks"]}
        self.assertIn("unbound iMessage jobs remain", checks["P6-IMSGSERVICES"]["message"])

        for _ in range(2):
            result = subprocess.run(
                ["bash", str(ROOT / "install.sh"), "--imessage-only", "--no-verify"],
                env=self.env, capture_output=True, text=True, timeout=20, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        stage = self.home / ".wideband" / "imessage" / "launchagents"
        disabled = self.home / ".wideband" / "imessage" / "disabled-launchagents"
        for job in jobs:
            label = f"com.example.imessage-{job}"
            self.assertFalse((self.la / f"{label}.plist").exists())
            self.assertFalse((self.loaded / label).exists())
            self.assertTrue((stage / f"{label}.plist").is_file())
            self.assertEqual(len(list(disabled.glob(f"*/{label}.plist"))), 1)
            self.assertIn(f"bootout gui/{os.getuid()}/{label}", self.log.read_text())
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "operator plist\n")
        self.assertNotIn("com.other", self.log.read_text())

        after = subprocess.run(
            ["bash", str(ROOT / "verify.sh"), "--imessage-only", "--json"],
            env=self.env, capture_output=True, text=True, timeout=20, check=False,
        )
        checks = {check["id"]: check for check in json.loads(after.stdout)["checks"]}
        self.assertIn("staged outside LaunchAgents", checks["P6-IMSGSERVICES"]["message"])

    def test_bound_install_waits_for_live_exact_target_before_loading(self):
        cfg = self.home / ".wideband" / "imessage" / "config.json"
        runtime.atomic_json(cfg, {"schema_version": 1, "binding": {
            "chat_id": 7, "chat_guid": CHAT["guid"], "account_login": AGENT_ACCOUNT,
        }})
        command = ["bash", str(ROOT / "install.sh"), "--imessage-only", "--no-verify"]
        result = subprocess.run(command, env=self.env, capture_output=True,
                                text=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("does not match the live owner chat", result.stdout)
        self.assertFalse(list(self.la.glob("com.example.imessage-*.plist")))

        agent = self.home / "Applications" / "Wideband Agent.app" / "Contents" / "MacOS" / "Wideband Agent"
        agent.write_text("#!/bin/sh\necho '{\"target_verified\":true}'\n", encoding="utf-8")
        agent.chmod(0o755)
        result = subprocess.run(command, env=self.env, capture_output=True,
                                text=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for job in ("watch", "route", "keep", "outbox"):
            label = f"com.example.imessage-{job}"
            self.assertTrue((self.la / f"{label}.plist").is_file())
            self.assertTrue((self.loaded / label).is_file())
        self.assertNotIn("send ", self.log.read_text())


if __name__ == "__main__":
    unittest.main()
