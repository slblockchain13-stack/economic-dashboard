"""Tests for the local server (run_local.py): who may call the API, and how AI requests are run.
Run: python3 -m unittest discover -s tests"""
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import run_local as R  # noqa: E402


def call(port, path, method="GET", headers=None, body=None, host=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, data=body, headers=headers or {})
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        with e:
            return e.code, e.read()


class LocalServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        R.Handler.log_message = lambda *a, **k: None      # keep the test output quiet
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), R.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        # a stand-in for the claude command: prints its arguments and the prompt it was given
        cls.tmp = tempfile.TemporaryDirectory()
        fake = Path(cls.tmp.name) / "claude"
        fake.write_text('#!/bin/sh\nprintf "ARGS:%s\\n" "$*"\nprintf "CWD:%s\\n" "$(pwd)"\ncat\n')
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        cls.fake = str(fake)
        cls.real_claude_path = R.claude_path

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()
        R.claude_path = cls.real_claude_path

    def setUp(self):
        R.claude_path = lambda: self.fake

    H = {"Content-Type": "application/json", "X-Dashboard": "local"}

    def test_serves_the_page_and_status(self):
        code, body = call(self.port, "/index.html")
        self.assertEqual(code, 200)
        self.assertIn(b"Economic Machine Monitor", body)
        code, body = call(self.port, "/api/status")
        self.assertEqual((code, json.loads(body)["local"], json.loads(body)["claude"]), (200, True, True))

    def test_files_outside_docs_are_not_served(self):
        self.assertEqual(call(self.port, "/../run_local.py")[0], 404)
        self.assertEqual(call(self.port, "/bot/update.py")[0], 404)

    def test_other_websites_and_other_hosts_cannot_use_the_api(self):
        body = json.dumps({"prompt": "hello"}).encode()
        self.assertEqual(call(self.port, "/api/ask", "POST", {"Content-Type": "application/json"}, body)[0], 403)                 # no page header
        self.assertEqual(call(self.port, "/api/ask", "POST", {**self.H, "Origin": "https://evil.example"}, body)[0], 403)        # another site
        self.assertEqual(call(self.port, "/api/ask", "POST", self.H, body, host="evil.example")[0], 403)                         # DNS rebinding
        self.assertEqual(call(self.port, "/api/refresh", "POST", {"Content-Type": "application/json"}, b"{}")[0], 403)
        self.assertEqual(call(self.port, "/api/status", host="evil.example")[0], 403)

    def test_ask_runs_claude_with_tools_off_in_an_empty_folder(self):
        code, body = call(self.port, "/api/ask", "POST", self.H, json.dumps({"prompt": "DATA BRIEF\nMY QUESTION: why?"}).encode())
        d = json.loads(body)
        self.assertEqual((code, d["ok"]), (200, True))
        args = d["text"].splitlines()[0]
        for flag in ("-p", "--tools  --strict-mcp-config", "--disable-slash-commands", "--no-session-persistence", "--system-prompt"):
            self.assertIn(flag, args)
        self.assertIn("MY QUESTION: why?", d["text"])                       # the prompt arrives on standard input
        cwd = next(l for l in d["text"].splitlines() if l.startswith("CWD:"))[4:]
        self.assertNotIn(str(ROOT), os.path.realpath(cwd))                  # not run inside the project
        self.assertFalse(os.path.exists(cwd))                               # and the folder is gone afterwards

    def test_bad_requests(self):
        self.assertEqual(call(self.port, "/api/ask", "POST", self.H, json.dumps({"prompt": "  "}).encode())[0], 400)
        self.assertEqual(call(self.port, "/api/ask", "POST", self.H, json.dumps({"prompt": "x" * (R.MAX_PROMPT + 1)}).encode())[0], 400)
        self.assertEqual(call(self.port, "/api/ask", "POST", self.H, b"not json")[0], 400)
        self.assertEqual(call(self.port, "/api/nothing", "POST", self.H, b"{}")[0], 404)

    def test_missing_or_failing_claude_gives_a_plain_message(self):
        R.claude_path = lambda: None
        d = json.loads(call(self.port, "/api/ask", "POST", self.H, json.dumps({"prompt": "q"}).encode())[1])
        self.assertFalse(d["ok"])
        self.assertIn("Copy", d["text"])
        bad = Path(self.tmp.name) / "claude-bad"
        bad.write_text("#!/bin/sh\necho 'not signed in' >&2\nexit 1\n")
        bad.chmod(bad.stat().st_mode | stat.S_IEXEC)
        R.claude_path = lambda: str(bad)
        d = json.loads(call(self.port, "/api/ask", "POST", self.H, json.dumps({"prompt": "q"}).encode())[1])
        self.assertFalse(d["ok"])
        self.assertIn("not signed in", d["text"])


if __name__ == "__main__":
    unittest.main()
