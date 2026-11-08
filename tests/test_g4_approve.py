"""G4 (OATHLINE_GUARD_PLAN sections 5 and 10, as amended after FABLE 15:47): `oathline-guard approve`, the person's window.

It prints the Guard's own text for each waiting call, re-hashes it and records SHOWN, takes what the person types and records HEARD;
the right code is the yes ROW, `n` is a RECORDED no, a wrong code decides nothing and asks again. It never confirms and never runs:
the Guard process does, on the agent's next identical call. It refuses to read from anything but a terminal (an agent's shell tool
cannot type the code), and refuses to start without the person the Guard was started with.

  A1 piped stdin: refused before anything is shown or heard (a real subprocess)
  A2 the right code: SHOWN, HEARD, the yes row; the agent's next identical call runs it once; what was shown is what the record holds
  A3 n: a recorded no; the agent's next call is told so; nothing runs
  A4 a wrong code, then the right one: asked again, nothing decided in between, then one run
  A5 approve.py never calls confirm / confirm_from_yes / set_executor / register (an AST test)
  A6 two live processes under load: eight proposals approved in one window while the Guard serves; each runs exactly once
  A7 nothing waiting: says so, exits 0; no human recorded: refused, exit 2
"""
import ast
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
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


class G4Case(unittest.TestCase):
    SERVER = "db"

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="oathline-guard-g4-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.home = os.path.join(self.root, "home")

    def start(self, upstream_argv, reads=()):
        path = os.path.join(self.root, "reads.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"server": self.SERVER, "reads": list(reads)}, fh)
        g = Client([sys.executable, "-m", "oathline_guard", "run", "--server", self.SERVER, "--reads", path, "--home", self.home,
                    "--human", HUMAN, "--", *upstream_argv], extra_env={"FAKE_LOG": os.path.join(self.root, "upstream.log")})
        self.addCleanup(g.close)
        g.start()
        return g

    def fake_db(self):
        self.state = os.path.join(self.root, "db.json")
        return self.start(fake_db_argv(self.state))

    def db(self):
        with open(self.state, encoding="utf-8") as fh:
            return json.load(fh)

    def approve(self, answers, *, isatty=True):
        """Run the window in-process with scripted answers. Each answer is a str, or a callable(record, call) -> str."""
        from oathline_guard import approve
        from oathline_guard.record import Record
        rec = Record(os.path.join(self.home, self.SERVER), self.SERVER)
        self.addCleanup(rec.close)
        out = io.StringIO()
        queue = list(answers)

        def ask(prompt, call):
            a = queue.pop(0) if queue else "n"
            return a(rec, call) if callable(a) else a
        n = approve.window(rec, ask=ask, out=out, isatty=lambda: isatty, once=True)
        return n, out.getvalue(), rec

    def events(self, kind=None):
        log = AuditLog(os.path.join(self.home, self.SERVER, "audit.db"), chain_id=f"oathline-guard-{self.SERVER}")
        try:
            return [e for e in log.events() if kind is None or e["event_type"] == kind]
        finally:
            log.close()


def right_code(rec, call):
    return rec.code(call)


class A1_NotATerminal(G4Case):
    def test_a1(self):
        g = self.fake_db()
        g.tool("drop_database", {"name": "prod"})
        p = subprocess.run([sys.executable, "-m", "oathline_guard", "approve", "--server", "db", "--home", self.home, "--once"],
                           input="ABCD\n", capture_output=True, text=True, encoding="utf-8", cwd=_core.ROOT, env=env(), timeout=60)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("terminal", p.stderr.lower())
        self.assertEqual(self.events("SHOWN"), [])
        self.assertEqual(self.events("HEARD"), [])

    def test_a1_in_process(self):
        g = self.fake_db()
        g.tool("drop_database", {"name": "prod"})
        from oathline_guard import approve
        with self.assertRaises(approve.NotATerminal):
            self.approve([right_code], isatty=False)
        self.assertEqual(self.events("HEARD"), [])


class A2_TheYes(G4Case):
    def test_a2(self):
        g = self.fake_db()
        g.tool("drop_database", {"name": "staging"})
        n, out, rec = self.approve([right_code])
        self.assertEqual(n, 1)
        self.assertIn("db / drop_database", out)
        self.assertIn("name: staging", out)
        shown = self.events("SHOWN")
        self.assertEqual(len(shown), 1)
        printed = out[out.index("db / drop_database"):]
        text = printed[:printed.index("code: ") + len("code: ") + 4]
        self.assertEqual(shown[0]["payload"]["text_sha256"], hashlib.sha256(text.encode("utf-8")).hexdigest())   # what was shown
        self.assertEqual(len(self.events("HEARD")), 1)
        self.assertEqual(self.events("CONFIRMED_BY_HUMAN"), [])                                # approve never confirms
        r = g.tool("drop_database", {"name": "staging"})["result"]
        self.assertFalse(r["isError"], r)
        self.assertNotIn("staging", self.db())
        self.assertEqual(len(self.events("EXECUTED")), 1)


class A3_TheNo(G4Case):
    def test_a3(self):
        g = self.fake_db()
        g.tool("drop_database", {"name": "prod"})
        self.approve(["n"])
        r = g.tool("drop_database", {"name": "prod"})["result"]
        self.assertIn("said no", r["content"][0]["text"])
        self.assertIn("prod", self.db())
        self.assertEqual(self.events("EXECUTED"), [])


class A4_WrongThenRight(G4Case):
    def test_a4(self):
        g = self.fake_db()
        g.tool("drop_database", {"name": "staging"})
        n, out, rec = self.approve(["ZZZZ", right_code])
        self.assertIn("Wrong code", out)
        self.assertEqual(len(self.events("SHOWN")), 1)
        r = g.tool("drop_database", {"name": "staging"})["result"]
        self.assertFalse(r["isError"], r)
        self.assertEqual(len(self.events("EXECUTED")), 1)
        self.assertEqual(self.events("CONFIRM_REFUSED"), [])


class A5_NeverConfirms(unittest.TestCase):
    def test_a5(self):
        src = open(os.path.join(_core.ROOT, "oathline_guard", "approve.py"), encoding="utf-8").read()
        bad = [f"line {n.lineno}: .{n.func.attr}(" for n in ast.walk(ast.parse(src))
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr in ("confirm", "confirm_from_yes", "set_executor", "register", "request", "propose")]
        self.assertEqual(bad, [])


class A6_TwoProcessesUnderLoad(G4Case):
    SERVER = "up"

    def test_a6(self):
        g = self.start([sys.executable, "-m", "tests.fake_upstreams", "pages"])
        for i in range(8):
            g.tool("write_b", {"n": str(i)})
        n, out, rec = self.approve([right_code] * 8)
        self.assertEqual(n, 8)
        for i in range(8):
            r = g.tool("write_b", {"n": str(i)})["result"]
            self.assertFalse(r["isError"], (i, r))
        for i in range(8):
            g.tool("write_b", {"n": str(i)})                                   # delivered already: a NEW proposal each, nothing runs
        with open(os.path.join(self.root, "upstream.log"), encoding="utf-8") as fh:
            calls = [json.loads(ln) for ln in fh if ln.strip()]
        self.assertEqual(sum(1 for c in calls if c.get("call") == "write_b"), 8)
        self.assertEqual(len(self.events("EXECUTED")), 8)


class A7_Edges(G4Case):
    def test_a7_nothing_waiting(self):
        self.fake_db()
        n, out, rec = self.approve([])
        self.assertEqual(n, 0)
        self.assertIn("Nothing is waiting", out)

    def test_a7_no_guard_record(self):
        os.makedirs(os.path.join(self.home, "db"), exist_ok=True)
        code, out, err = run_main(["--server", "db", "--home", self.home, "--once"])     # in-process (FABLE 20:29)
        self.assertEqual(code, 2)
        self.assertIn("--human", err)


if __name__ == "__main__":
    unittest.main()
