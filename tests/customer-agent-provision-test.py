#!/usr/bin/env python3
"""Isolated customer roster and map contract; never uses the live tmux socket."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class ProvisionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="wbap-", dir="/tmp")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        home = root / "home"
        home.mkdir(mode=0o700)
        socket_dir = root / "sockets"
        socket_dir.mkdir(mode=0o700)
        # An inherited TMUX points at the operator's live server and overrides
        # TMUX_TMPDIR. Clear it before any test command, including cleanup.
        inherited_tmux = os.environ.pop("TMUX", None)
        self.addCleanup(lambda: os.environ.__setitem__("TMUX", inherited_tmux)
                        if inherited_tmux is not None else os.environ.pop("TMUX", None))
        os.environ["HOME"] = str(home)
        os.environ["TMUX_TMPDIR"] = str(socket_dir)
        tmux = shutil.which("tmux")
        self.assertIsNotNone(tmux)
        os.environ["FLEETDECK_VERIFIED_TMUX"] = str(Path(tmux).resolve())
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging"))
        import customer_agent_provision as provision
        self.provision = provision
        self.tmux = str(Path(tmux).resolve())
        self.addCleanup(lambda: subprocess.run([self.tmux, "kill-server"],
                                               env={k: v for k, v in os.environ.items() if k != "TMUX"},
                                               stdout=subprocess.DEVNULL,
                                               stderr=subprocess.DEVNULL, check=False))

    def test_seed_create_and_map_are_truthful(self):
        p = self.provision
        p.seed_default_roster()
        revision = p._read()["revision"]
        p.seed_default_roster()
        self.assertEqual(revision, p._read()["revision"])
        self.assertEqual(p.ROSTER.stat().st_mode & 0o777, 0o600)
        states = {item["name"]: item["state"] for item in p.list_agents()}
        self.assertEqual(states, {"wb-head": "planned", "website": "awaiting_project",
                                  "research": "planned", "qa": "planned"})
        with self.assertRaisesRegex(ValueError, "actual website project"):
            p.activate_agent("website")
        with self.assertRaisesRegex(ValueError, "authenticated"):
            p.activate_agent("wb-head")
        project = Path.home() / "srv" / "client-site"
        project.mkdir(parents=True)
        website = p.create_agent({"name": "website", "role": "website",
                                  "workspace": str(project)})
        self.assertEqual(website["state"], "planned")
        self.assertEqual(p.create_agent({"name": "website", "role": "website",
                                          "workspace": str(project)})["state"], "planned")
        with self.assertRaisesRegex(ValueError, "different role"):
            p.create_agent({"name": "website", "role": "qa", "workspace": str(project)})
        with self.assertRaisesRegex(ValueError, "owns only wb-head"):
            p.create_agent({"name": "other-head", "role": "head", "workspace": ""})
        with self.assertRaisesRegex(ValueError, "ordinary directory"):
            p.create_agent({"name": "unsafe", "role": "qa", "workspace": str(Path.home()/".ssh")})

        subprocess.run([self.tmux, "new-session", "-d", "-s", "occupied",
                        "-c", str(project), "/bin/sleep", "120"],
                       check=True, capture_output=True)
        with self.assertRaisesRegex(ValueError, "unregistered tmux session"):
            p.create_agent({"name": "occupied", "role": "general", "workspace": str(project)})
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging" /
                               "customer_fleet_map"))
        from customer_fleet_map import snapshot
        from customer_fleet_map.reader import validate_snapshot
        args = type("Args", (), {"host_id": "local", "sessions_conf": None,
                                   "devices_conf": None})()
        raw, _ = snapshot.collect(args)
        clean = validate_snapshot(raw)
        agent_nodes = [n for n in clean["nodes"] if n["type"] == "agent"]
        self.assertEqual(len(agent_nodes), 4)
        self.assertTrue(all(n["registry"]["state"] == "planned" for n in agent_nodes))
        self.assertEqual(clean["summary"]["verified_agent_nodes"], 0)
        self.assertEqual(clean["summary"]["process_observed_agent_nodes"], 0)
        self.assertEqual(sum(e["type"] == "planned_binding" for e in clean["edges"]), 4)

        compiler = shutil.which("cc")
        if compiler is None:
            self.skipTest("C compiler unavailable for an isolated provider process")
        version_dir = Path.home() / ".local" / "share" / "claude" / "versions"
        version_dir.mkdir(parents=True)
        provider = version_dir / "2.1.220"
        source = ("#include <stdio.h>\n#include <string.h>\n#include <unistd.h>\n"
                  "int main(int argc, char **argv) {\n"
                  "  if (argc == 4 && strcmp(argv[1], \"auth\") == 0) {\n"
                  "    puts(\"{\\\"loggedIn\\\":true}\"); return 0;\n"
                  "  }\n  sleep(120); return 0;\n}\n")
        subprocess.run([compiler, "-x", "c", "-o", str(provider), "-"], input=source,
                       text=True, capture_output=True, check=True)
        link = Path.home() / ".local" / "bin" / "claude"
        link.parent.mkdir(parents=True)
        link.symlink_to(provider)
        self.assertEqual(p._provider(), str(provider.resolve()))
        fifth = p.create_agent({"name": "fifth", "role": "general", "workspace": ""})
        self.assertEqual(fifth["state"], "planned")
        self.assertEqual(p.activate_agent("fifth")["state"], "process_observed")
        self.assertEqual(p.activate_agent("fifth")["state"], "process_observed")
        raw, _ = snapshot.collect(args)
        clean = validate_snapshot(raw)
        self.assertEqual(clean["summary"]["verified_agent_nodes"], 1)
        self.assertEqual(sum(e["type"] == "verified_binding" for e in clean["edges"]), 1)
        self.assertEqual(sum(e["type"] == "occupies" for e in clean["edges"]), 1)
        self.assertEqual(next(n for n in clean["nodes"] if n["id"] == "agent:fifth")
                         ["registry"]["state"], "verified")


if __name__ == "__main__":
    unittest.main()
