"""`oathline-guard demo` (Claude 00:58 Tue 10 Nov item 4: shorten the 5-minute quickstart for the Show HN reader), red first.

The command only PREPARES: it writes the read list and the demo database's state file into one folder and prints the Claude
Desktop block with that machine's real paths (the Python interpreter and the scripts, absolute), so nothing is typed by hand and
the "python vs python3" and "not on PATH" problems cannot happen. It approves nothing and runs nothing (no scripted person in the
package: the scripted scene stays in examples/, which is not shipped).

  M1  `demo --dir D --human you` writes D/reads.json (the two reads) and prints valid JSON for claude_desktop_config.json whose
      command is an absolute, existing file and whose args name D's absolute paths, the human, `--`, the same interpreter and
      the demo server; then the next two steps (the approve window, the sentence to ask)
  M2  the printed block really starts the guard: spawned as printed, it answers tools/list with the demo's four tools
  M3  an existing reads.json is left as it is (said on stdout), never overwritten
  M4  the CLI's usage names `demo`; the package holds no scripted approver (no module under oathline_guard/ calls rec.code())
"""
import ast
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests import _core
from tests.client import Client, env


def run_demo(*args):
    return subprocess.run([sys.executable, "-m", "oathline_guard", "demo", *args], capture_output=True, text=True,
                          encoding="utf-8", cwd=_core.ROOT, env=env(), timeout=60, stdin=subprocess.DEVNULL)


def printed_config(stdout):
    m = re.search(r"(\{\s*\"mcpServers\".*?\n\})", stdout, re.S)
    assert m, stdout
    return json.loads(m.group(1))


class Demo(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="og-demo-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_m1_writes_and_prints(self):
        p = run_demo("--dir", self.dir, "--human", "you")
        self.assertEqual(p.returncode, 0, p.stderr)
        with open(os.path.join(self.dir, "reads.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {"server": "db", "reads": ["list_databases", "list_tables"]})
        entry = printed_config(p.stdout)["mcpServers"]["db"]
        self.assertTrue(os.path.isabs(entry["command"]) and os.path.isfile(entry["command"]), entry["command"])
        args = entry["args"]
        cut = args.index("--")
        flags = args[:cut]
        self.assertEqual(flags[flags.index("--reads") + 1], os.path.join(os.path.abspath(self.dir), "reads.json"))
        self.assertEqual(flags[flags.index("--human") + 1], "you")
        self.assertEqual(flags[flags.index("--server") + 1], "db")
        tail = args[cut + 1:]
        self.assertTrue(os.path.isabs(tail[0]) and os.path.isfile(tail[0]))
        self.assertEqual(tail[1:3], ["-m", "oathline_guard.demo.fake_db"])
        self.assertEqual(tail[tail.index("--state") + 1], os.path.join(os.path.abspath(self.dir), "db.json"))
        self.assertIn("oathline-guard approve --server db", p.stdout)
        self.assertIn(f"{os.path.abspath(sys.executable)} -m oathline_guard approve --server db", p.stdout)   # FABLE 02:00 nit: no PATH needed
        self.assertIn("clean up the old database", p.stdout)

    def test_m2_the_printed_block_starts_the_guard(self):
        p = run_demo("--dir", self.dir, "--human", "you")
        entry = printed_config(p.stdout)["mcpServers"]["db"]
        home = os.path.join(self.dir, "home")
        args = list(entry["args"])
        args[args.index("--") : args.index("--")] = ["--home", home]        # keep the test's record out of ~
        c = Client([entry["command"], *args])
        self.addCleanup(c.close)
        c.start()
        self.assertEqual({t["name"] for t in c.tools()}, {"list_databases", "list_tables", "drop_database", "delete_backups"})

    def test_m3_existing_read_list_kept(self):
        path = os.path.join(self.dir, "reads.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('{"server": "db", "reads": ["list_databases"]}')
        p = run_demo("--dir", self.dir, "--human", "you")
        self.assertEqual(p.returncode, 0, p.stderr)
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["reads"], ["list_databases"])
        self.assertIn("kept", p.stdout)


class M4_NoScriptedApprover(unittest.TestCase):
    def test_m4(self):
        from oathline_guard.__main__ import USAGE
        self.assertIn("demo", USAGE)
        for f in glob.glob(os.path.join(_core.ROOT, "oathline_guard", "**", "*.py"), recursive=True):
            tree = ast.parse(open(f, encoding="utf-8").read())
            calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                     and n.func.attr == "code" and not f.endswith("record.py") and not f.endswith("approve.py")]
            self.assertEqual(calls, [], f)


if __name__ == "__main__":
    unittest.main()
