#!/usr/bin/env python3
"""The customer Fleetdeck bundle never inherits another profile's tools."""

import ast
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "customer_fleetdeck_bundler", ROOT / "packaging" / "bundle-fleetdeck.py")
bundler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundler)


class CustomerPortalToolchainTest(unittest.TestCase):
    def test_first_portal_launch_has_system_only_path(self):
        upstream = ('<?xml version="1.0"?>\n<plist><dict><key>PATH</key><string>'
                    + bundler.UPSTREAM_PORTAL_PATH + '</string></dict></plist>\n')
        customer = bundler.customer_portal_template(upstream)
        self.assertIn('<string>' + bundler.INITIAL_PORTAL_PATH + '</string>', customer)
        self.assertNotIn('/opt/homebrew', customer)
        self.assertNotIn('/usr/local/bin', customer)
        self.assertNotIn('__HOME__/bin', customer)
        with self.assertRaisesRegex(ValueError, 'PATH changed'):
            bundler.customer_portal_template(upstream.replace('/opt/homebrew/bin', '/other/bin'))

    def test_customer_portal_closes_operator_imsg_binary(self):
        source = '''from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os, re, json
PAGE = """#cashflow #cashflow #cashflow #cashflow #cashflow
<a id="cashflow" href="/cashflow"
     title="Cashflow — the accountant's cash view">__CASHFLOW_LABEL__</a>"""
NOTES_PAGE = """ function ago(ts){
   var s = Math.max(0, Math.floor(Date.now()/1000 - ts));
}"""
INTERNAL = {8784}
SEED_NOTES = []
OPERATOR_PHONE = ""
TRACE_IMESSAGE_HANDLE = ""
NETMAP_URL = ""
CASHFLOW_PATH = ""
WHISPER_MODEL = ""
VOICE_URL = ""
NOTES_PATH = ""
TRACE_SESSION = "trace"
IMSG = "/opt/homebrew/bin/imsg"
def send_text(text): return IMSG
def scan(): pass
def onboarding_config(): pass
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path
        if path == "/healthz": pass
    def do_POST(self): pass
def main():
    ThreadingHTTPServer((BIND, PORT), Handler)
'''
        customer = bundler.customer_portal(source)
        assignments = [node for node in ast.parse(customer).body
                       if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == 'IMSG'
                               for target in node.targets)]
        self.assertEqual(len(assignments), 1)
        self.assertEqual(ast.literal_eval(assignments[0].value), '')
        self.assertNotIn('/opt/homebrew/bin/imsg', customer)

    def test_customer_chat_drops_foreign_tool_fallbacks(self):
        source = '''def _bin(name, *fallbacks): return name
TMUX = _bin("tmux", "/opt/homebrew/bin/tmux", "/usr/local/bin/tmux")
TTYD = _bin("ttyd", "/opt/homebrew/bin/ttyd", "/usr/local/bin/ttyd")
'''
        customer = bundler.customer_chat_tools(source)
        self.assertIn('TMUX = _bin("tmux")', customer)
        self.assertIn('TTYD = _bin("ttyd")', customer)
        self.assertNotIn('/opt/homebrew', customer)
        self.assertNotIn('/usr/local/bin', customer)
        with self.assertRaisesRegex(ValueError, 'assignment changed: TTYD'):
            bundler.customer_chat_tools(source.replace('TTYD =', 'TTYD_BIN ='))


if __name__ == '__main__':
    unittest.main()
