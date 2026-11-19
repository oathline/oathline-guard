"""The Guard on Core 0.3.0 (Claude 03:50 Wed AGENT item 3; branch core-0.3.0 from the released e457dbb; version 0.2.0 in the code only,
not on PyPI).

  C1  the Guard runs on Core 0.3.x and asks for it: pyproject depends on "oathline>=0.3.0,<0.4"; the version is 0.2.0 everywhere
      (pyproject, __version__, server.json and its package, CHANGELOG's top entry, a RELEASE_NOTES_0.2.0.md draft)
  L1  `oathline-guard log --server NAME [--home DIR] [--since N]` prints the server's Core events after N as JSON lines, using Core's
      own `events(since_seq=N)` (seq is in every event's hashed body), read-only: the audit file's bytes and time are unchanged
  L2  `log ... --verify` prints Core's verify report for the same range (from_seq) and exits 1 when it does not hold
  L3  a server with no record: exit 2, and nothing is created
"""
import contextlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from tests import _core  # noqa: F401
from oathline import AuditLog

import oathline_guard
from oathline_guard.__main__ import main


def read(*p):
    with open(os.path.join(_core.ROOT, *p), encoding="utf-8") as fh:
        return fh.read()


class C1_Versions(unittest.TestCase):
    def test_c1(self):
        import oathline
        self.assertTrue(oathline.__version__.startswith("0.3."), oathline.__version__)
        self.assertIn('dependencies = ["oathline>=0.3.0,<0.4"]', read("pyproject.toml"))
        self.assertEqual(oathline_guard.__version__, "0.2.0")
        self.assertIn('version = "0.2.0"', read("pyproject.toml"))
        s = json.loads(read("server.json"))
        self.assertEqual((s["version"], [p["version"] for p in s["packages"]]), ("0.2.0", ["0.2.0"]))
        self.assertTrue(read("CHANGELOG.md").split("\n## ", 1)[1].startswith("0.2.0"))
        self.assertTrue(os.path.isfile(os.path.join(_core.ROOT, "RELEASE_NOTES_0.2.0.md")))


class _Log(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="guard-log-")
        self.addCleanup(shutil.rmtree, self.home, True)
        folder = os.path.join(self.home, "db")
        os.makedirs(folder)
        self.path = os.path.join(folder, "audit.db")
        log = AuditLog(self.path, chain_id="oathline-guard-db")
        for i in range(5):
            log.append("EVENT", "oathline-guard", "tool/db/x", {"n": i})
        log.close()

    def run_main(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(list(argv))
        return rc, buf.getvalue()


class L1_Since(_Log):
    def test_l1(self):
        before = (os.path.getmtime(self.path), os.path.getsize(self.path))
        rc, out = self.run_main("log", "--server", "db", "--home", self.home, "--since", "2")
        self.assertEqual(rc, 0, out)
        rows = [json.loads(ln) for ln in out.splitlines() if ln.strip()]
        self.assertEqual([r["seq"] for r in rows], [3, 4])
        rc, out = self.run_main("log", "--server", "db", "--home", self.home)
        self.assertEqual(len([ln for ln in out.splitlines() if ln.strip()]), 5)
        self.assertEqual((os.path.getmtime(self.path), os.path.getsize(self.path)), before)


class L2_Verify(_Log):
    def test_l2(self):
        rc, out = self.run_main("log", "--server", "db", "--home", self.home, "--since", "1", "--verify")
        self.assertEqual(rc, 0, out)
        self.assertTrue(json.loads(out.splitlines()[-1])["ok"])
        db = sqlite3.connect(self.path)
        db.execute("DROP TRIGGER audit_no_update")
        db.execute("UPDATE audit SET payload='{\"n\":9}' WHERE seq=3")
        db.commit()
        db.close()
        rc, out = self.run_main("log", "--server", "db", "--home", self.home, "--since", "1", "--verify")
        self.assertEqual(rc, 1, out)


class L3_NoRecord(_Log):
    def test_l3(self):
        rc, _ = self.run_main("log", "--server", "nope", "--home", self.home)
        self.assertEqual(rc, 2)
        self.assertFalse(os.path.exists(os.path.join(self.home, "nope")))


if __name__ == "__main__":
    unittest.main()
