"""THE ACCEPTANCE TEST (OATHLINE_GUARD_PLAN section 9; Claude 15:05 / 16:15): the PocketOS quickstart, end to end, by the clock.

The incident it stops: an AI agent deleted a production database and its backups in nine seconds, with no approval step (April 2026).
Here a scripted agent (an MCP client standing in for the model) talks to fake-db-mcp through oathline-guard; the person answers in
`oathline-guard approve` (scripted answers, the window's own code); the record is read by the oathline-agent CLI.

Pass = in under 5 minutes by this test's clock: the agent's reads pass; delete_backups("prod") and drop_database("prod") are shown
exactly and refused by the person; a coded yes to drop_database("staging") runs it once; the agent's switch back to "prod" is a new
proposal that runs nothing; prod and every backup are intact and staging is gone; `oathline-agent unheard` finds 0 rows; `heard` on
the staging call says SHOWN = HEARD = CONFIRMED = RUN; `oathline-agent verify` says the chain is ok.
"""
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
from tests.client import Client, fake_db_argv

HUMAN = "saroj"
AGENT_REPO = os.environ.get("OATHLINE_AGENT_PATH") or os.path.join(os.path.dirname(_core.ROOT), "oathline-agent")


class PocketOSQuickstart(unittest.TestCase):
    def setUp(self):
        self.t0 = time.monotonic()
        self.root = tempfile.mkdtemp(prefix="oathline-guard-quickstart-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.home = os.path.join(self.root, "home")
        self.state = os.path.join(self.root, "db.json")
        reads = os.path.join(self.root, "reads.json")
        with open(reads, "w", encoding="utf-8") as fh:                    # what `init` will write (G6): the operator's read list
            json.dump({"server": "db", "reads": ["list_databases", "list_tables"]}, fh)
        self.agent = Client([sys.executable, "-m", "oathline_guard", "run", "--server", "db", "--reads", reads, "--home", self.home,
                             "--human", HUMAN, "--"] + fake_db_argv(self.state))
        self.addCleanup(self.agent.close)
        self.agent.start()

    def db(self):
        with open(self.state, encoding="utf-8") as fh:
            return json.load(fh)

    def person(self, *answers):
        """The approve window, answering what is waiting now. 'CODE' types the code shown; anything else is typed as it is."""
        from oathline_guard import approve
        from oathline_guard.record import Record
        rec = Record(os.path.join(self.home, "db"), "db")
        try:
            out, queue = io.StringIO(), list(answers)
            approve.window(rec, ask=lambda prompt, call: rec.code(call) if queue.pop(0) == "CODE" else "n", out=out,
                           isatty=lambda: True, once=True)
            return out.getvalue()
        finally:
            rec.close()

    def tokens(self):
        from oathline_guard.record import Record
        rec = Record(os.path.join(self.home, "db"), "db")
        try:
            return {(r[0], json.loads(r[1]).get("name")): r[2] for r in rec.db.execute("SELECT tool, arguments, token FROM calls ORDER BY created")}
        finally:
            rec.close()

    def oathline_agent(self, *argv):
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([_core.CORE, AGENT_REPO, _core.ROOT]), PYTHONIOENCODING="utf-8",
                   OATHLINE_GUARD_HOME=self.home, OATHLINE_GUARD_SERVER="db")
        folder = os.path.join(self.home, "db")
        p = subprocess.run([sys.executable, "-m", "oathline_agent", "--audit", os.path.join(folder, "audit.db"), "--tokens",
                            os.path.join(folder, "tokens.db"), "--registry", "oathline_guard.registry:for_server", *argv],
                           capture_output=True, text=True, encoding="utf-8", env=env, timeout=120)
        return p.returncode, p.stdout + p.stderr

    def text(self, r):
        return r["result"]["content"][0]["text"]

    def test_the_quickstart(self):
        # the agent looks around: reads pass
        self.assertEqual(json.loads(self.text(self.agent.tool("list_databases"))), ["prod", "staging"])

        # "clean up the old database": first the backups of prod, then prod itself
        self.assertIn("Not run", self.text(self.agent.tool("delete_backups", {"name": "prod"})))
        shown = self.person("n")
        self.assertIn("db / delete_backups", shown)
        self.assertIn("name: prod", shown)
        self.assertNotIn("Free space", shown)                                    # never the server's own soothing words
        self.assertIn("said no", self.text(self.agent.tool("delete_backups", {"name": "prod"})))

        self.assertIn("Not run", self.text(self.agent.tool("drop_database", {"name": "prod"})))
        shown = self.person("n")
        self.assertIn("db / drop_database", shown)
        self.assertIn("said no", self.text(self.agent.tool("drop_database", {"name": "prod"})))

        # the person agrees to the staging copy, with the code; it runs once
        self.assertIn("Not run", self.text(self.agent.tool("drop_database", {"name": "staging"})))
        self.person("CODE")
        r = self.agent.tool("drop_database", {"name": "staging"})["result"]
        self.assertFalse(r["isError"], r)
        self.assertIn("dropped staging", r["content"][0]["text"])

        # the agent switches back to prod with the same tool: a new proposal; nothing runs without a new yes
        self.assertIn("Not run", self.text(self.agent.tool("drop_database", {"name": "prod"})))

        # the world: prod and every backup intact, staging gone
        world = self.db()
        self.assertIn("prod", world)
        self.assertEqual(world["prod"]["backups"], ["prod-2026-11-07", "prod-2026-11-08"])
        self.assertNotIn("staging", world)

        # the record, read by the oathline-agent CLI
        code, out = self.oathline_agent("unheard")
        self.assertIn("0 unheard", out, out)
        code, out = self.oathline_agent("verify")
        self.assertEqual(code, 0, out)
        self.assertIn("chain: ok", out)
        staging = self.tokens()[("drop_database", "staging")]
        code, out = self.oathline_agent("heard", staging)
        self.assertEqual(code, 0, out)
        self.assertIn("SHOWN = HEARD = CONFIRMED = RUN", out)

        self.assertLess(time.monotonic() - self.t0, 300, "the quickstart must take under five minutes")


class TheExample(unittest.TestCase):
    def test_examples_stop_the_delete_runs(self):
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([_core.CORE, _core.ROOT]), PYTHONIOENCODING="utf-8")
        p = subprocess.run([sys.executable, os.path.join(_core.ROOT, "examples", "stop_the_delete.py")], capture_output=True,
                           text=True, encoding="utf-8", env=env, timeout=180, cwd=_core.ROOT)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        for line in ("prod and its backups: intact", "staging: dropped once", "chain ok: True"):
            self.assertIn(line, p.stdout)


if __name__ == "__main__":
    unittest.main()
