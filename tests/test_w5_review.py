"""FABLE's review of W5 (11:42 Mon 9 Nov 2026), red first. All local.

  V1  git_commit commits exactly the files it names (shown in the window), and refuses when anything else is modified or
      untracked (an untracked .env beside the approved edit is never committed)
  V2  open_pr never follows a redirect: a fake API that answers 302 to a second local server: that server never sees the
      request (or the token), and the call is an error
  V6  the recipe denies the Windows shell too (PowerShell), and the README's start check names it
  V7  the base branch is protected whatever its spelling: refs/heads/main, MAIN, Main are refused
"""
import http.server
import json
import os
import sys
import threading
import unittest

from tests import _core
from tests.test_w5_fix_path import FIX, NEW, OLD, FixPath, _PRApi, git, text_of


class _Second(http.server.BaseHTTPRequestHandler):
    seen: list = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        _Second.seen.append({"path": self.path, "auth": self.headers.get("Authorization")})
        self.send_response(201)
        self.end_headers()
        self.wfile.write(b"{}")

    do_GET = do_POST


class Review(FixPath):
    def test_v1_exact_files_and_stray_refused(self):
        self.held_then_yes(self.fs, "fs", "edit_file", self.edit())
        with open(os.path.join(self.site, ".env"), "w", encoding="utf-8") as fh:
            fh.write("PR_TOKEN=secret\n")
        window, out, err = self.held_then_yes(self.git, "git", "git_commit",
                                              {"branch": "truth-fix", "message": "x", "files": ["index.html"]})
        self.assertIn("index.html", window)
        self.assertTrue(err, out)
        self.assertIn(".env", out)
        self.assertNotIn("truth-fix", git(self.site, "branch", "--list", "truth-fix"))       # nothing committed
        os.remove(os.path.join(self.site, ".env"))
        _, out, err = self.held_then_yes(self.git, "git", "git_commit",
                                         {"branch": "truth-fix", "message": "x", "files": ["index.html"]})
        self.assertFalse(err, out)
        self.assertEqual(json.loads(out)["files"], ["index.html"])

    def test_v1_files_is_required(self):
        tool = [t for t in self.git.tools() if t["name"] == "git_commit"][0]
        self.assertIn("files", tool["inputSchema"]["required"])

    def test_v2_pr_redirect_not_followed(self):
        second = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Second)
        threading.Thread(target=second.serve_forever, daemon=True).start()
        self.addCleanup(second.server_close)
        self.addCleanup(second.shutdown)
        _Second.seen.clear()

        class _Redir(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                self.send_response(302)                 # urllib follows a 302 on POST (as a GET), keeping Authorization
                self.send_header("Location", f"http://localhost:{second.server_address[1]}/pulls")
                self.end_headers()
        redir = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Redir)
        threading.Thread(target=redir.serve_forever, daemon=True).start()
        self.addCleanup(redir.server_close)
        self.addCleanup(redir.shutdown)
        git_r = self.guard("git2", ["git_status", "git_diff"],
                           [sys.executable, os.path.join(FIX, "fix_git.py"), "--repo", self.site, "--base", "main", "--remote", "origin"],
                           extra_env={"FIX_PR_API": f"http://127.0.0.1:{redir.server_address[1]}/pulls", "FIX_PR_TOKEN": "tok-xyz"})
        _, out, err = self.held_then_yes(git_r, "git2", "open_pr", {"branch": "truth-fix", "title": "t", "body": "b"})
        self.assertTrue(err, out)
        self.assertEqual(_Second.seen, [])

    def test_v7_base_branch_any_spelling(self):
        self.held_then_yes(self.fs, "fs", "edit_file", self.edit())
        for b in ("refs/heads/main", "MAIN", "Main"):
            first, err = text_of(self.git.tool("git_commit", {"branch": b, "message": "x", "files": ["index.html"]}))
            self.person("git", "CODE")
            out, err = text_of(self.git.tool("git_commit", {"branch": b, "message": "x", "files": ["index.html"]}))
            self.assertTrue(err, (b, out))
            self.assertIn("base branch", out)


class V6_Recipe(unittest.TestCase):
    def test_v6(self):
        with open(os.path.join(FIX, "claude_settings.json"), encoding="utf-8") as fh:
            deny = set(json.load(fh)["permissions"]["deny"])
        self.assertIn("PowerShell", deny)
        with open(os.path.join(FIX, "README.md"), encoding="utf-8") as fh:
            self.assertIn("PowerShell", fh.read())


if __name__ == "__main__":
    unittest.main()
