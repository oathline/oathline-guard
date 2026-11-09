"""SITE_WATCH W5 = Stage 1 of the fix path's authority ladder, built (SITE_WATCH_PLAN_2026-11-09 sections 2.3 and 2.5; Claude 11:20
Mon 9 Nov 2026), red first. Everything here is LOCAL: a fixture site repository, a local BARE repository as its remote, and a
local fake pull-request API (an HTTP server on 127.0.0.1). Nothing touches a real remote.

The coding agent's only write tools are two MCP servers run behind oathline-guard (examples/fix_path/):
  fix_fs   read_file, list_directory (reads); edit_file(path, old_text, new_text) (held; one exact replacement per call, flat
           strings so the window shows each verbatim: on one line when short, as a gutter block when multi-line or long)
  fix_git  git_status, git_diff (reads); git_commit(branch, message), git_push(branch, commit), open_pr(branch, title, body)
           (held); no force, no delete, no push to the base branch; the PR token is the server's (env), never an argument

  W5a edit_file waits for the coded yes; nothing is written before it; the window shows the path and each oldText / newText
      verbatim (a multi-line new text as a gutter block); after the yes the file holds exactly the shown new text
  W5b git_commit, then git_push of a BRANCH: each waits for its own yes; after them the remote has that branch at exactly the
      approved commit, and its diff from main is exactly the approved edit; main is untouched
  W5c the push runs ONCE: the agent's next identical call after it ran is a new request that waits (nothing pushed again)
  W5d refused on any change: a yes for one push does not run a push with other arguments (another branch, another commit)
  W5e open_pr runs once after its yes: the fake PR API gets exactly one request, with the server's token in its header; the
      token is in no argument, no shown text and no file the guard writes
  W5f the base branch is never pushed, even with a yes (the server refuses it); there is no force and no delete tool
  W5g the session recipe: Claude Code's own Edit / Write / MultiEdit / NotebookEdit / Bash are denied, and every MCP server in
      the recipe is started through `oathline-guard run` with a read list that holds no write tool
"""
import http.server
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

from tests import _core
from tests.client import Client

HUMAN = "saroj"
TOKEN = "fixture-pr-token-5c1f9e"
FIX = os.path.join(_core.ROOT, "examples", "fix_path")
HOME_PAGE = "<html><body>\n<h1>Nexxt Test Site</h1>\n<p>The bridge is live.</p>\n</body></html>\n"
OLD = "<p>The bridge is live.</p>"
NEW = "<p>Oathline Core is public: version 0.2.0 is on PyPI.</p>"


def git(cwd, *args):
    p = subprocess.run(["git", "-c", "core.autocrlf=false", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if p.returncode:
        raise AssertionError(f"git {args}: {p.stderr}")
    return p.stdout.strip()


class _PRApi(http.server.BaseHTTPRequestHandler):
    calls: list = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8")
        _PRApi.calls.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": json.loads(body)})
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"number": len(_PRApi.calls), "url": f"http://pr.local/{len(_PRApi.calls)}"}).encode())


def text_of(resp):
    res = resp.get("result") or {}
    return "\n".join(c.get("text", "") for c in res.get("content") or []), bool(res.get("isError"))


class FixPath(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="w5-fix-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.site = os.path.join(self.root, "site")
        self.remote = os.path.join(self.root, "remote.git")
        os.makedirs(self.site)
        git(self.root, "init", "-q", "--bare", self.remote)
        git(self.site, "init", "-q", "-b", "main")
        with open(os.path.join(self.site, "index.html"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(HOME_PAGE)
        git(self.site, "add", "index.html")
        git(self.site, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-q", "-m", "the site")
        git(self.site, "remote", "add", "origin", self.remote)
        git(self.site, "push", "-q", "origin", "main")
        self.main_sha = git(self.remote, "rev-parse", "main")
        _PRApi.calls.clear()
        self.api = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _PRApi)
        threading.Thread(target=self.api.serve_forever, daemon=True).start()
        self.addCleanup(self.api.server_close)
        self.addCleanup(self.api.shutdown)
        self.home = os.path.join(self.root, "guard-home")
        self.fs = self.guard("fs", ["read_file", "list_directory"],
                             [sys.executable, os.path.join(FIX, "fix_fs.py"), "--root", self.site])
        self.git = self.guard("git", ["git_status", "git_diff"],
                              [sys.executable, os.path.join(FIX, "fix_git.py"), "--repo", self.site, "--base", "main",
                               "--remote", "origin"],
                              extra_env={"FIX_PR_API": f"http://127.0.0.1:{self.api.server_address[1]}/pulls",
                                         "FIX_PR_TOKEN": TOKEN, "FIX_GIT_NAME": "SIYA fix session",
                                         "FIX_GIT_EMAIL": "siya-fix@example.invalid"})

    def guard(self, server, reads, upstream, extra_env=None):
        path = os.path.join(self.root, f"reads-{server}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"server": server, "reads": reads}, fh)
        c = Client([sys.executable, "-m", "oathline_guard", "run", "--server", server, "--reads", path, "--home", self.home,
                    "--human", HUMAN, "--"] + upstream, extra_env=extra_env)
        self.addCleanup(c.close)
        c.start()
        return c

    def person(self, server, *answers):
        """The approve window for `server`, answering what waits now: 'CODE' types the shown code, anything else is typed."""
        from oathline_guard import approve
        from oathline_guard.record import Record
        rec = Record(os.path.join(self.home, server), server)
        try:
            out, queue = io.StringIO(), list(answers)
            approve.window(rec, ask=lambda prompt, call: rec.code(call) if queue.pop(0) == "CODE" else "n", out=out,
                           isatty=lambda: True, once=True)
            return out.getvalue()
        finally:
            rec.close()

    def held_then_yes(self, client, server, tool, args):
        """The agent asks, waits, the person says yes with the code, the agent asks again: -> (window text, the run's text)."""
        first, err = text_of(client.tool(tool, args))
        self.assertTrue(err and "waiting for a person's yes" in first, first)
        window = self.person(server, "CODE")
        second, err2 = text_of(client.tool(tool, args))
        return window, second, err2

    def read_site(self):
        with open(os.path.join(self.site, "index.html"), encoding="utf-8", newline="") as fh:
            return fh.read()

    def edit(self):
        return {"path": "index.html", "old_text": OLD, "new_text": NEW}

    # ------------------------------------------------------------------ W5a
    def test_w5a_edit_waits_and_writes_exactly_the_shown_text(self):
        first, err = text_of(self.fs.tool("edit_file", self.edit()))
        self.assertTrue(err and "waiting" in first)
        self.assertEqual(self.read_site(), HOME_PAGE)                           # nothing written before the yes
        window = self.person("fs", "CODE")
        self.assertIn("fs / edit_file", window)
        self.assertIn("index.html", window)
        self.assertIn("old_text: " + OLD, window)
        self.assertIn("new_text: " + NEW, window)
        out, err = text_of(self.fs.tool("edit_file", self.edit()))
        self.assertFalse(err, out)
        self.assertEqual(self.read_site(), HOME_PAGE.replace(OLD, NEW))

    def test_w5a_multiline_new_text_is_a_block(self):
        new = "<p>Oathline Core is public.</p>\n<p>Version 0.2.0 is on PyPI.</p>"
        args = {"path": "index.html", "old_text": OLD, "new_text": new}
        window, out, err = self.held_then_yes(self.fs, "fs", "edit_file", args)
        self.assertFalse(err, out)
        self.assertIn("new_text:\n| <p>Oathline Core is public.</p>\n| <p>Version 0.2.0 is on PyPI.</p>\n--- end of new_text ---", window)
        self.assertEqual(self.read_site(), HOME_PAGE.replace(OLD, new))

    def test_w5a_reads_pass(self):
        out, err = text_of(self.fs.tool("read_file", {"path": "index.html"}))
        self.assertFalse(err)
        self.assertIn(OLD, out)

    # ------------------------------------------------------------------ W5b / W5c / W5d
    def commit_and_push(self):
        self.held_then_yes(self.fs, "fs", "edit_file", self.edit())
        _, out, err = self.held_then_yes(self.git, "git", "git_commit", {"branch": "truth-fix", "message": "Say what is true"})
        self.assertFalse(err, out)
        sha = json.loads(out)["commit"]
        window, out, err = self.held_then_yes(self.git, "git", "git_push", {"branch": "truth-fix", "commit": sha})
        self.assertFalse(err, out)
        return sha, window

    def test_w5b_branch_pushed_at_the_approved_commit(self):
        sha, window = self.commit_and_push()
        self.assertIn("branch: truth-fix", window)
        self.assertIn("commit: " + sha, window)
        self.assertEqual(git(self.remote, "rev-parse", "refs/heads/truth-fix"), sha)
        self.assertEqual(git(self.remote, "rev-parse", "main"), self.main_sha)
        diff = git(self.remote, "diff", "main", "truth-fix")
        self.assertIn("-" + OLD, diff)
        self.assertIn("+" + NEW, diff)
        self.assertEqual([l for l in diff.splitlines() if l.startswith(("+<", "-<"))], ["-" + OLD, "+" + NEW])

    def test_w5c_the_push_runs_once(self):
        sha, _ = self.commit_and_push()
        again, err = text_of(self.git.tool("git_push", {"branch": "truth-fix", "commit": sha}))
        self.assertTrue(err and "waiting" in again, again)                      # a new request, not a second run

    def test_w5d_a_yes_does_not_carry_to_other_arguments(self):
        self.held_then_yes(self.fs, "fs", "edit_file", self.edit())
        _, out, _ = self.held_then_yes(self.git, "git", "git_commit", {"branch": "truth-fix", "message": "Say what is true"})
        sha = json.loads(out)["commit"]
        first, err = text_of(self.git.tool("git_push", {"branch": "truth-fix", "commit": sha}))
        self.assertTrue(err)
        self.person("git", "CODE")
        other, err = text_of(self.git.tool("git_push", {"branch": "elsewhere", "commit": sha}))
        self.assertTrue(err and "waiting" in other, other)
        refs = git(self.remote, "for-each-ref", "--format=%(refname)")
        self.assertNotIn("refs/heads/elsewhere", refs)
        self.assertNotIn("refs/heads/truth-fix", refs)                          # the approved call has not been made yet

    # ------------------------------------------------------------------ W5e
    def test_w5e_pr_once_with_the_servers_token(self):
        self.commit_and_push()
        args = {"branch": "truth-fix", "title": "Say what is true", "body": "Two sentences corrected."}
        window, out, err = self.held_then_yes(self.git, "git", "open_pr", args)
        self.assertFalse(err, out)
        self.assertEqual(len(_PRApi.calls), 1)
        call = _PRApi.calls[0]
        self.assertEqual(call["auth"], f"Bearer {TOKEN}")
        self.assertEqual((call["body"]["head"], call["body"]["base"], call["body"]["title"]), ("truth-fix", "main", "Say what is true"))
        self.assertNotIn(TOKEN, window)
        for dirpath, _, files in os.walk(self.home):
            for f in files:
                with open(os.path.join(dirpath, f), "rb") as fh:
                    self.assertNotIn(TOKEN.encode(), fh.read(), f)
        again, err = text_of(self.git.tool("open_pr", args))
        self.assertTrue(err and "waiting" in again)
        self.assertEqual(len(_PRApi.calls), 1)

    # ------------------------------------------------------------------ W5f
    def test_w5f_base_branch_never_pushed(self):
        self.held_then_yes(self.fs, "fs", "edit_file", self.edit())
        _, out, _ = self.held_then_yes(self.git, "git", "git_commit", {"branch": "truth-fix", "message": "x"})
        sha = json.loads(out)["commit"]
        _, out, err = self.held_then_yes(self.git, "git", "git_push", {"branch": "main", "commit": sha})
        self.assertTrue(err, out)
        self.assertIn("base branch", out)
        self.assertEqual(git(self.remote, "rev-parse", "main"), self.main_sha)

    def test_w5f_no_force_no_delete_tools(self):
        names = {t["name"] for t in self.git.tools()} | {t["name"] for t in self.fs.tools()}
        self.assertEqual(names, {"read_file", "list_directory", "edit_file", "git_status", "git_diff", "git_commit", "git_push",
                                 "open_pr"})
        push = [t for t in self.git.tools() if t["name"] == "git_push"][0]
        self.assertEqual(set(push["inputSchema"]["properties"]), {"branch", "commit"})


class W5g_TheRecipe(unittest.TestCase):
    def test_w5g_native_tools_denied_and_every_server_guarded(self):
        with open(os.path.join(FIX, "claude_settings.json"), encoding="utf-8") as fh:      # `claude --settings`
            s = json.load(fh)
        self.assertTrue({"Edit", "Write", "MultiEdit", "NotebookEdit", "Bash"} <= set(s["permissions"]["deny"]))
        with open(os.path.join(FIX, "mcp.json"), encoding="utf-8") as fh:                  # `claude --mcp-config ... --strict-mcp-config`
            servers = json.load(fh)["mcpServers"]
        self.assertEqual(set(servers), {"fs", "git"})
        for name, entry in servers.items():
            self.assertEqual(entry["command"], "oathline-guard", name)
            args = entry["args"]
            self.assertEqual(args[:3], ["run", "--server", name])
            reads_path = args[args.index("--reads") + 1]
            with open(os.path.join(FIX, os.path.basename(reads_path)), encoding="utf-8") as fh:
                reads = json.load(fh)["reads"]
            self.assertFalse(set(reads) & {"edit_file", "git_commit", "git_push", "open_pr"}, name)


if __name__ == "__main__":
    unittest.main()
