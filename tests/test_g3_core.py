"""G3 (OATHLINE_GUARD_PLAN section 10, as amended after FABLE 15:47): Core inside the Guard.

A held call becomes a Core 0.2.0 heard proposal (capability mcp/<server>/<tool>, one item per argument): the words are the Guard's
(a single-line value as itself or as an escaped literal; a long or multi-line value carried by its hash with a short said, shown
WHOLE behind a "| " gutter); the agent gets a deferred answer (the call, where to approve, the expiry; never the code). The human side
(record.py: text, re-hash + show, hear, the yes ROW, the no) is what G4's `approve` wraps; here the tests play it. Only the Guard
process confirms, from the yes row, and runs the STORED arguments once; a retry matches an UNRESOLVED call (or delivers a resolved
call's outcome once), an identical call after that is a new proposal; a no is a recorded outcome.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

from tests import _core  # noqa: F401
from tests.client import Client, fake_db_argv
from oathline import AuditLog

HUMAN = "saroj"


class G3Case(unittest.TestCase):
    READS = ["list_databases", "list_tables"]

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="oathline-guard-g3-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.state = os.path.join(self.root, "db.json")
        self.home = os.path.join(self.root, "home")
        reads = os.path.join(self.root, "reads.json")
        with open(reads, "w", encoding="utf-8") as fh:
            json.dump({"server": "db", "reads": self.READS}, fh)
        argv = [sys.executable, "-m", "oathline_guard", "run", "--server", "db", "--reads", reads, "--home", self.home,
                "--human", HUMAN, "--"] + fake_db_argv(self.state)
        self.g = Client(argv)
        self.addCleanup(self.g.close)
        self.g.start()

    def record(self):
        from oathline_guard.record import Record
        r = Record(os.path.join(self.home, "db"), "db")
        self.addCleanup(r.close)
        return r

    def db(self):
        with open(self.state, encoding="utf-8") as fh:
            return json.load(fh)

    def events(self, kind=None):
        log = AuditLog(os.path.join(self.home, "db", "audit.db"), chain_id="oathline-guard-db")
        try:
            self.assertTrue(log.verify()["ok"])
            return [e for e in log.events() if kind is None or e["event_type"] == kind]
        finally:
            log.close()

    def text_of(self, r):
        return r["result"]["content"][0]["text"] if "result" in r else json.dumps(r)

    def approve(self, call, *, code=None, text=None):
        """What G4's `approve` does: the text, the re-hash + SHOWN, HEARD, the yes row (code typed)."""
        rec = self.record()
        t = text if text is not None else rec.text(call)
        shown = rec.show(call, t)
        self.assertTrue(shown.get("ok"), shown)
        self.assertTrue(rec.hear(call).get("ok"))
        rec.yes(call, code if code is not None else rec.code(call), HUMAN)
        return t


class T1_Deferred(G3Case):
    def test_t1_a_held_call_is_a_proposal_and_a_deferred_answer(self):
        before = self.db()
        r = self.g.tool("drop_database", {"name": "prod"})["result"]
        self.assertTrue(r["isError"])
        text = r["content"][0]["text"]
        self.assertIn("Not run", text)
        self.assertIn("oathline-guard approve", text)
        calls = self.record().pending()
        self.assertEqual(len(calls), 1)
        self.assertIn(calls[0]["call"], text)                    # the call is named
        self.assertNotIn(self.record().code(calls[0]["call"]), text)   # the code never crosses the client pipe
        self.assertEqual(self.db(), before)                     # nothing reached the server
        p = self.events("PROPOSED_BY_AGENT")
        self.assertEqual(len(p), 1)
        self.assertEqual(p[0]["action"], "mcp/db/drop_database")
        self.assertIsNotNone(p[0]["payload"].get("items_hash"))


class T2_TheWords(G3Case):
    def test_t2_every_argument_no_description_the_code_last(self):
        self.g.tool("drop_database", {"name": "prod"})
        rec = self.record()
        call = rec.pending()[0]["call"]
        lines = rec.text(call).split("\n")
        self.assertEqual(lines[0], "db / drop_database")
        self.assertIn("name: prod", lines)
        self.assertNotIn("Tidy up", "\n".join(lines))          # the server's own description is never the words
        self.assertTrue(lines[-1].startswith("code: "))
        self.assertEqual(sum(1 for ln in lines if ln.startswith("code:")), 1)

    def test_t3_a_value_cannot_write_a_gate_line(self):
        self.g.tool("drop_database", {"name": "prod\nname: staging (a copy)\ncode: ZZZZ"})
        rec = self.record()
        lines = rec.text(rec.pending()[0]["call"]).split("\n")
        self.assertEqual(sum(1 for ln in lines if ln.startswith("code:")), 1)
        self.assertEqual(sum(1 for ln in lines if ln.startswith("name:")), 1)
        self.assertTrue(lines[-1].startswith("code: "))

    def test_t4_a_long_value_is_a_block_behind_the_gutter_with_a_short_said(self):
        sql = "DELETE FROM users WHERE id IN (" + ",".join(str(i) for i in range(2500)) + ");\ncode: ZZZZ\n--- end of name ---"
        r = self.g.tool("drop_database", {"name": sql})
        self.assertIn("Not run", self.text_of(r))
        rec = self.record()
        text = rec.text(rec.pending()[0]["call"])
        self.assertIn("name:", text.split("\n"))
        self.assertIn("| code: ZZZZ", text.split("\n"))
        self.assertEqual(sum(1 for ln in text.split("\n") if ln.startswith("code:")), 1)
        item = self.events("PROPOSED_BY_AGENT")[0]
        self.assertTrue(item["payload"].get("items_hash"))


class T5_RetryAndRun(G3Case):
    def test_t5_retry_before_the_yes_is_the_same_proposal(self):
        self.g.tool("drop_database", {"name": "staging"})
        self.g.tool("drop_database", {"name": "staging"})
        self.assertEqual(len(self.events("PROPOSED_BY_AGENT")), 1)
        self.assertEqual(len(self.record().pending()), 1)

    def test_t6_the_yes_then_the_retry_runs_once_with_the_stored_arguments(self):
        self.g.tool("drop_database", {"name": "staging"})
        call = self.record().pending()[0]["call"]
        self.approve(call)
        r = self.g.tool("drop_database", {"name": "staging"})["result"]
        self.assertFalse(r["isError"], r)
        self.assertIn("dropped staging", r["content"][0]["text"])
        self.assertNotIn("staging", self.db())
        self.assertIn("prod", self.db())
        kinds = [e["event_type"] for e in self.events()]
        self.assertEqual(kinds.count("EXECUTED"), 1)
        for k in ("SHOWN", "HEARD", "CONFIRMED_BY_HUMAN", "EXECUTING", "EXECUTED"):
            self.assertIn(k, kinds)

    def test_t7_an_identical_call_after_the_outcome_was_delivered_is_a_new_proposal(self):
        self.g.tool("drop_database", {"name": "staging"})
        self.approve(self.record().pending()[0]["call"])
        self.g.tool("drop_database", {"name": "staging"})           # runs and is delivered
        r = self.g.tool("drop_database", {"name": "staging"})       # next week, the same call: asked again
        self.assertIn("Not run", self.text_of(r))
        self.assertEqual(len(self.events("PROPOSED_BY_AGENT")), 2)
        self.assertEqual(len(self.events("EXECUTED")), 1)

    def test_t8_changed_arguments_are_a_new_proposal(self):
        self.g.tool("drop_database", {"name": "staging"})
        self.g.tool("drop_database", {"name": "prod"})
        self.assertEqual(len(self.events("PROPOSED_BY_AGENT")), 2)


class T9_TheNo(G3Case):
    def test_t9_a_no_is_recorded_and_never_runs(self):
        self.g.tool("drop_database", {"name": "prod"})
        rec = self.record()
        call = rec.pending()[0]["call"]
        rec.show(call, rec.text(call))
        rec.hear(call)
        rec.no(call, HUMAN)
        r = self.g.tool("drop_database", {"name": "prod"})["result"]
        self.assertTrue(r["isError"])
        self.assertIn("said no", r["content"][0]["text"])
        self.assertIn("prod", self.db())
        self.assertEqual(self.events("EXECUTED"), [])
        rec.yes(call, rec.code(call), HUMAN)                      # a yes after the no is too late
        self.g.tool("drop_database", {"name": "prod"})
        self.assertIn("prod", self.db())
        self.assertEqual(self.events("EXECUTED"), [])


class T10_WrongCode(G3Case):
    def test_t10_a_wrong_code_runs_nothing(self):
        self.g.tool("drop_database", {"name": "staging"})
        call = self.record().pending()[0]["call"]
        self.approve(call, code="XXXX")
        r = self.g.tool("drop_database", {"name": "staging"})["result"]
        self.assertTrue(r["isError"])
        self.assertIn("staging", self.db())
        self.assertEqual(self.events("EXECUTED"), [])


class T11_ReHash(G3Case):
    def test_t11_a_block_that_does_not_hash_is_not_shown(self):
        self.g.tool("drop_database", {"name": "x" * 600 + "\nline two"})
        rec = self.record()
        call = rec.pending()[0]["call"]
        good = rec.text(call)
        bad = good.replace("| line two", "| line TWO")
        self.assertEqual(rec.show(call, bad).get("error"), "shown_body_differs")
        self.assertEqual(self.events("SHOWN"), [])
        self.assertTrue(rec.show(call, good).get("ok"))


class T12_UpstreamError(G3Case):
    def test_t12_an_upstream_error_is_execute_failed(self):
        self.g.tool("drop_database", {"name": "nope"})
        self.approve(self.record().pending()[0]["call"])
        r = self.g.tool("drop_database", {"name": "nope"})["result"]
        self.assertTrue(r["isError"])
        self.assertIn("no database", r["content"][0]["text"])
        self.assertEqual(len(self.events("EXECUTE_FAILED")), 1)
        self.assertEqual(self.events("EXECUTED"), [])


class T13_NoHuman(unittest.TestCase):
    def test_t13_without_a_human_nothing_can_be_asked(self):
        root = tempfile.mkdtemp(prefix="oathline-guard-g3-nohuman-")
        self.addCleanup(shutil.rmtree, root, True)
        reads = os.path.join(root, "reads.json")
        with open(reads, "w", encoding="utf-8") as fh:
            json.dump({"server": "db", "reads": []}, fh)
        g = Client([sys.executable, "-m", "oathline_guard", "run", "--server", "db", "--reads", reads, "--home", os.path.join(root, "h"),
                    "--"] + fake_db_argv(os.path.join(root, "db.json")))
        self.addCleanup(g.close)
        g.start()
        r = g.tool("drop_database", {"name": "prod"})["result"]
        self.assertTrue(r["isError"])
        self.assertIn("no person is configured", r["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
