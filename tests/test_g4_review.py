"""FABLE's review of G4 (mailbox 20:01 Sun 8 Nov 2026), red first.

  W1 an expired proposal is never printed (no text, no code), never SHOW_REFUSED; the window says "expired" once
  W2 a call shown and left unanswered (three wrong codes) is not re-shown or re-heard on the next rounds of the same window
  W3 a console that cannot encode the text: nothing printed, nothing SHOWN, the window says it cannot display it and goes on
  W4 the AST rule, stronger: approve.py imports exactly argparse, os, sys, time and .record; no getattr / __import__ / importlib;
     __main__.py never confirms either
  W5 approve --server takes the run side's name rule; a record started WITHOUT --human refuses (exit 2)
"""
import ast
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from tests import _core
from tests.client import Client, env, fake_db_argv
from oathline import AuditLog

HUMAN = "saroj"


def run_main(argv, *, stdout=None):
    """approve.main() in-process with the terminal check passing (FABLE 20:29: a subprocess inherits the RUNNER's stdin, which is
    not a terminal under CI, so the branch under test was never reached there). -> (exit code, stdout text, stderr text)."""
    import contextlib
    from unittest import mock
    from oathline_guard import approve
    out = stdout if stdout is not None else io.StringIO()
    err = io.StringIO()
    with mock.patch.object(approve, "_stdin_is_terminal", lambda: True), mock.patch("builtins.input", lambda prompt="": "n"), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = approve.main(list(argv))
    return code, (out.getvalue() if isinstance(out, io.StringIO) else ""), err.getvalue()


class Case(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="oathline-guard-g4r-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.home = os.path.join(self.root, "home")
        reads = os.path.join(self.root, "reads.json")
        with open(reads, "w", encoding="utf-8") as fh:
            json.dump({"server": "db", "reads": []}, fh)
        self.g = Client([sys.executable, "-m", "oathline_guard", "run", "--server", "db", "--reads", reads, "--home", self.home,
                         "--human", HUMAN, "--"] + fake_db_argv(os.path.join(self.root, "db.json")))
        self.addCleanup(self.g.close)
        self.g.start()

    def rec(self, **kw):
        from oathline_guard.record import Record
        r = Record(os.path.join(self.home, "db"), "db", **kw)
        self.addCleanup(r.close)
        return r

    def events(self, kind):
        log = AuditLog(os.path.join(self.home, "db", "audit.db"), chain_id="oathline-guard-db")
        try:
            return [e for e in log.events() if e["event_type"] == kind]
        finally:
            log.close()

    def window(self, rec, answers, *, out=None, rounds=1):
        from oathline_guard import approve
        out = out if out is not None else io.StringIO()
        queue = list(answers)
        kw = {"max_rounds": rounds, "poll": 0} if rounds > 1 else {}
        approve.window(rec, ask=lambda p, call: queue.pop(0) if queue else "", out=out, isatty=lambda: True, once=(rounds == 1), **kw)
        return out


class W1_Expired(Case):
    def test_w1(self):
        from oathline_guard.record import TTL_SECONDS
        self.g.tool("drop_database", {"name": "prod"})
        later = time.time() + TTL_SECONDS + 5
        rec = self.rec(clock=lambda: later)
        code = rec.code(rec.db.execute("SELECT call FROM calls").fetchone()[0])
        out = self.window(rec, [], rounds=3).getvalue()
        self.assertNotIn("name: prod", out)
        self.assertNotIn(code, out)
        self.assertEqual(out.count("expired"), 1, out)
        self.assertEqual(self.events("SHOW_REFUSED"), [])
        self.assertEqual(rec.pending(), [])


class W2_NoReshow(Case):
    def test_w2(self):
        self.g.tool("drop_database", {"name": "staging"})
        rec = self.rec()
        out = self.window(rec, ["AAAA", "BBBB", "CCCC", "DDDD", "EEEE", "FFFF"], rounds=3).getvalue()
        self.assertEqual(out.count("db / drop_database"), 1, out)
        self.assertEqual(len(self.events("SHOWN")), 1)
        self.assertEqual(len(self.events("HEARD")), 1)


class W3_Console(Case):
    def test_w3_cannot_encode(self):
        self.g.tool("drop_database", {"name": "日本"})
        rec = self.rec()
        raw = io.BytesIO()
        out = io.TextIOWrapper(raw, encoding="cp1252", errors="strict", write_through=True)
        self.window(rec, ["n"], out=out)
        printed = raw.getvalue().decode("cp1252")
        self.assertIn("cannot display", printed)
        self.assertNotIn("db / drop_database", printed)
        self.assertEqual(self.events("SHOWN"), [])

    def test_w3_utf8_console_shows(self):
        self.g.tool("drop_database", {"name": "日本"})
        rec = self.rec()
        raw = io.BytesIO()
        out = io.TextIOWrapper(raw, encoding="utf-8", write_through=True)
        self.window(rec, ["n"], out=out)
        self.assertIn("name: 日本", raw.getvalue().decode("utf-8"))
        self.assertEqual(len(self.events("SHOWN")), 1)


class W4_NeverConfirmsStronger(unittest.TestCase):
    def test_w4(self):
        for name in ("approve.py", "__main__.py"):
            src = open(os.path.join(_core.ROOT, "oathline_guard", name), encoding="utf-8").read()
            tree = ast.parse(src)
            bad = []
            for n in ast.walk(tree):
                if isinstance(n, ast.Call):
                    f = n.func
                    if isinstance(f, ast.Attribute) and f.attr in ("confirm", "confirm_from_yes", "set_executor", "register",
                                                                   "request", "propose"):
                        bad.append(f"{name}:{n.lineno} .{f.attr}(")
                    if isinstance(f, ast.Name) and f.id in ("getattr", "__import__", "exec", "eval"):
                        bad.append(f"{name}:{n.lineno} {f.id}(")
                if isinstance(n, (ast.Import, ast.ImportFrom)):
                    mods = [a.name for a in n.names] if isinstance(n, ast.Import) else [("." * n.level) + (n.module or "")]
                    bad += [f"{name}:{n.lineno} import {m}" for m in mods if m.split(".")[0] == "importlib"]
            self.assertEqual(bad, [], name)
        src = open(os.path.join(_core.ROOT, "oathline_guard", "approve.py"), encoding="utf-8").read()
        imported = set()
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.Import):
                imported |= {a.name for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                imported.add(("." * n.level) + (n.module or ""))
        self.assertEqual(imported - {"__future__"}, {"argparse", "os", "sys", "time", ".record"})


class W5_Names(unittest.TestCase):
    """In-process (FABLE 20:29): the subprocess form only reached these branches when the runner's own stdin was a terminal."""

    def test_w5_server_name_rule(self):
        root = tempfile.mkdtemp(prefix="oathline-guard-w5-")
        self.addCleanup(shutil.rmtree, root, True)
        code, out, err = run_main(["--server", "../other", "--home", root, "--once"])
        self.assertEqual(code, 2)
        self.assertIn("plain name", err)

    def test_w5_started_without_human(self):
        root = tempfile.mkdtemp(prefix="oathline-guard-w5-")
        self.addCleanup(shutil.rmtree, root, True)
        from oathline_guard.record import Record
        Record(os.path.join(root, "db"), "db", human="").close()
        code, out, err = run_main(["--server", "db", "--home", root, "--once"])
        self.assertEqual(code, 2)
        self.assertIn("--human", err)

    def test_w5_piped_stdin_is_refused_as_a_subprocess(self):
        root = tempfile.mkdtemp(prefix="oathline-guard-w5-")
        self.addCleanup(shutil.rmtree, root, True)
        p = subprocess.run([sys.executable, "-m", "oathline_guard", "approve", "--server", "db", "--home", root, "--once"],
                           input="", capture_output=True, text=True, encoding="utf-8", cwd=_core.ROOT, env=env(), timeout=60)
        self.assertEqual(p.returncode, 2)


class W6_MainDoesNotHideTheConsole(Case):
    """FABLE 20:29: main() reconfigured stdout to UTF-8, so the console check always passed and a cp1252 console got UTF-8 bytes
    while SHOWN hashed the real text. main() leaves the console as it is; a console that cannot encode the text is told so."""

    def test_w6(self):
        self.g.tool("drop_database", {"name": "\u65e5\u672c"})
        raw = io.BytesIO()
        cp1252 = io.TextIOWrapper(raw, encoding="cp1252", errors="strict", write_through=True)
        import contextlib
        from unittest import mock
        from oathline_guard import approve
        err = io.StringIO()
        with mock.patch.object(approve, "_stdin_is_terminal", lambda: True), mock.patch("builtins.input", lambda prompt="": "n"), \
                mock.patch.object(sys, "stdout", cp1252), contextlib.redirect_stderr(err):
            code = approve.main(["--server", "db", "--home", self.home, "--once"])
        printed = raw.getvalue().decode("cp1252", "replace")
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("cannot display", printed, err.getvalue())
        self.assertEqual(self.events("SHOWN"), [])



class W7_TheNoEvent(Case):
    """FABLE 21:17 nits: the REFUSED_BY_HUMAN event names the call and the channel; a no typed after the call expired writes no
    event for the expired token; window() resolves its terminal check when called."""

    def test_w7_payload(self):
        self.g.tool("drop_database", {"name": "prod"})
        rec = self.rec()
        self.window(rec, ["n"])
        ev = self.events("REFUSED_BY_HUMAN")
        self.assertEqual(len(ev), 1)
        call = rec.db.execute("SELECT call FROM calls").fetchone()[0]
        self.assertEqual(ev[0]["payload"].get("call"), call)
        self.assertEqual(ev[0]["payload"].get("channel"), "screen")

    def test_w7_no_after_expiry_writes_nothing(self):
        from oathline_guard.record import TTL_SECONDS
        self.g.tool("drop_database", {"name": "prod"})
        later = time.time() + TTL_SECONDS + 5
        rec = self.rec(clock=lambda: later)
        call = rec.db.execute("SELECT call FROM calls").fetchone()[0]
        rec.no(call, HUMAN)
        self.assertEqual(self.events("REFUSED_BY_HUMAN"), [])

    def test_w7_window_isatty_default_resolved_when_called(self):
        import inspect
        from oathline_guard import approve
        self.assertIsNone(inspect.signature(approve.window).parameters["isatty"].default)


if __name__ == "__main__":
    unittest.main()
