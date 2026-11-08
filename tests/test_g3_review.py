"""FABLE's review of G3 (mailbox 19:01 Sun 8 Nov 2026), red first, before G4 builds `approve` on these primitives.

  F1 a key starting with "_" is refused (it was shown and then dropped from the run)
  F2 a wrong code is not an answer: yes() refuses it, nothing is stored, the call stays pending, the right code then runs it
  F3 --shown-text keeps the shown words in the chain (D6); the default keeps only their hash
  F4 a --human that Core refuses (a non-human name) stops the Guard at start: exit 2, a stderr line
  F5 U+0085, U+2028, U+2029 (and every non-printable character) are escaped in a single-line value: no raw line breaker in the text
  N1 a protocol error during the run passes the upstream's own message back (EXECUTE_FAILED)
  N2 text_too_large is decided before Core's request(): no PROPOSED_BY_AGENT, no live token
  N3 60 declared 150-character values are one proposal (the budget counts a carried item as Core does)
  N4 confirm_from_yes() outside the Guard process refuses (not_the_guard_process): nothing confirmed, nothing burned
  N5 the human is in guard.db: the human side builds the same Registry without being told the name
  N6 a tool name with a newline heads the text on ONE line
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


def guard(root, upstream_argv, *, reads=(), human=HUMAN, extra=(), server="db"):
    path = os.path.join(root, "reads.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"server": server, "reads": list(reads)}, fh)
    argv = [sys.executable, "-m", "oathline_guard", "run", "--server", server, "--reads", path, "--home", os.path.join(root, "home"),
            *(["--human", human] if human else []), *extra, "--", *upstream_argv]
    return Client(argv, extra_env={"FAKE_LOG": os.path.join(root, "upstream.log")})


class Case(unittest.TestCase):
    SERVER = "db"

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="oathline-guard-g3r-")
        self.addCleanup(shutil.rmtree, self.root, True)

    def start(self, upstream_argv, **kw):
        g = guard(self.root, upstream_argv, server=self.SERVER, **kw)
        self.addCleanup(g.close)
        g.start()
        return g

    def fake_db(self, **kw):
        return self.start(fake_db_argv(os.path.join(self.root, "db.json")), **kw)

    def fake(self, mode, **kw):
        return self.start([sys.executable, "-m", "tests.fake_upstreams", mode], **kw)

    def record(self, **kw):
        from oathline_guard.record import Record
        r = Record(os.path.join(self.root, "home", self.SERVER), self.SERVER, **kw)
        self.addCleanup(r.close)
        return r

    def events(self, kind=None):
        log = AuditLog(os.path.join(self.root, "home", self.SERVER, "audit.db"), chain_id=f"oathline-guard-{self.SERVER}")
        try:
            return [e for e in log.events() if kind is None or e["event_type"] == kind]
        finally:
            log.close()

    def approve(self, call, code=None):
        rec = self.record()
        rec.show(call, rec.text(call))
        rec.hear(call)
        return rec.yes(call, code if code is not None else rec.code(call), HUMAN)


class F1_UnderscoreKey(Case):
    def test_f1(self):
        g = self.fake_db()
        r = g.tool("drop_database", {"name": "prod", "_force": True})["result"]
        self.assertTrue(r["isError"])
        self.assertIn("bad_argument_key", r["content"][0]["text"])
        self.assertEqual(self.record().pending(), [])


class F2_WrongCode(Case):
    def test_f2(self):
        g = self.fake_db()
        g.tool("drop_database", {"name": "staging"})
        call = self.record().pending()[0]["call"]
        self.assertFalse(self.approve(call, code="XXXX"))       # not an answer: nothing stored
        self.assertIsNone(self.record().answer(call))
        g.tool("drop_database", {"name": "staging"})
        self.assertEqual([c["call"] for c in self.record().pending()], [call])   # still pending, not burned
        self.assertTrue(self.record().yes(call, self.record().code(call), HUMAN))
        r = g.tool("drop_database", {"name": "staging"})["result"]
        self.assertFalse(r["isError"], r)
        self.assertEqual(len(self.events("EXECUTED")), 1)


class F3_ShownText(Case):
    def test_f3_default_hash_only(self):
        g = self.fake_db()
        g.tool("drop_database", {"name": "staging"})
        call = self.record().pending()[0]["call"]
        self.approve(call)
        self.assertNotIn("text", self.events("SHOWN")[0]["payload"])

    def test_f3_shown_text_switch(self):
        g = self.fake_db(extra=("--shown-text",))
        g.tool("drop_database", {"name": "staging"})
        call = self.record().pending()[0]["call"]
        self.approve(call)
        self.assertIn("db / drop_database", self.events("SHOWN")[0]["payload"].get("text", ""))


class F4_BadHuman(Case):
    def test_f4(self):
        g = guard(self.root, fake_db_argv(os.path.join(self.root, "db.json")), human="agent")
        self.addCleanup(g.close)
        self.assertEqual(g.p.wait(timeout=20), 2)
        import time
        time.sleep(0.3)
        self.assertIn("--human", "".join(g.stderr_lines))


class F5_LineBreakers(Case):
    def test_f5(self):
        g = self.fake_db()
        g.tool("drop_database", {"name": "prod code: ZZZZ\u0085x y"})
        rec = self.record()
        text = rec.text(rec.pending()[0]["call"])
        for ch in (" ", " ", "\u0085"):
            self.assertNotIn(ch, text)
        self.assertEqual(sum(1 for ln in text.splitlines() if ln.startswith("code:")), 1)


class N1_ProtocolError(Case):
    SERVER = "up"

    def test_n1(self):
        g = self.fake("protoerr")
        g.tool("write_b", {})
        self.approve(self.record().pending()[0]["call"])
        r = g.tool("write_b", {})["result"]
        self.assertTrue(r["isError"])
        self.assertIn("disk full", r["content"][0]["text"])
        self.assertEqual(len(self.events("EXECUTE_FAILED")), 1)


class N2_TooLargeBeforeCore(Case):
    def test_n2(self):
        g = self.fake_db()
        r = g.tool("drop_database", {"name": "x" * 17000})["result"]
        self.assertIn("text_too_large", r["content"][0]["text"])
        self.assertEqual(self.events("PROPOSED_BY_AGENT"), [])


class N3_Wide(Case):
    """Corrected before green: 60 carried items cost Core about 10 KB, over its 8 KB items cap, so no packing makes them one proposal.
    FABLE's point was the budget's undercount (the Guard handed Core what Core then refused); the Guard now counts an item at Core's
    measured size (oathline.tokens.items_text: about 200 bytes carried, 350 for a plain 150-character value), refuses BEFORE Core with
    the reason when even carrying cannot fit, and 30 such values are still one proposal (40 was my first guess: Core refused it)."""
    SERVER = "up"

    def test_n3_thirty_fit(self):
        g = self.fake("wide")
        r = g.tool("wide_write", {f"p{i}": "v" * 150 for i in range(30)})["result"]
        self.assertIn("waiting for a person", r["content"][0]["text"], r)
        self.assertEqual(len(self.events("PROPOSED_BY_AGENT")), 1)

    def test_n3_sixty_refused_before_core(self):
        g = self.fake("wide")
        r = g.tool("wide_write", {f"p{i}": "v" * 150 for i in range(60)})["result"]
        self.assertIn("items_too_large", r["content"][0]["text"])
        self.assertEqual(self.events("PROPOSED_BY_AGENT"), [])
        self.assertEqual(self.events("REQUEST_REFUSED"), [])


class N4_NotTheGuard(Case):
    def test_n4(self):
        g = self.fake_db()
        g.tool("drop_database", {"name": "staging"})
        call = self.record().pending()[0]["call"]
        self.approve(call)
        self.assertEqual(self.record().confirm_from_yes(call).get("error"), "not_the_guard_process")
        self.assertEqual(self.events("CONFIRMED_BY_HUMAN"), [])
        r = g.tool("drop_database", {"name": "staging"})["result"]        # the Guard still runs it
        self.assertFalse(r["isError"], r)


class N5_HumanInTheRecord(Case):
    def test_n5(self):
        g = self.fake_db()
        g.tool("drop_database", {"name": "staging"})
        self.assertEqual(self.record().human, HUMAN)


class N6_OddToolName(Case):
    """Corrected before green: Core cannot name a capability with a newline in it (printable characters only), so such a tool is
    never a capability: it is held and refused as 'cannot be shown', never proposed, and the Guard keeps serving."""
    SERVER = "up"

    def test_n6(self):
        g = self.fake("oddname")
        r = g.tool("write\ncode: ZZZZ", {"x": "1"})["result"]
        self.assertTrue(r["isError"])
        self.assertIn("cannot be shown", r["content"][0]["text"])
        self.assertEqual(self.record().pending(), [])
        self.assertIn("result", g.call("ping"))


if __name__ == "__main__":
    unittest.main()
