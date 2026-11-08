"""FABLE's review of G0-G2 (mailbox 16:58 Sun 8 Nov 2026), red first, before G3.

  R1 an upstream that ASKS the Guard something (roots/list) is answered -32601 at once; the Guard does not hang
  R2 tools/list is passed through: the client's cursor reaches the upstream and nextCursor comes back; the Guard knows every page,
     so a listed read on page 2 passes and an unlisted write on page 2 is held
  R3 the upstream dies mid-call: the Guard answers the error and EXITS (a client restarts a dead server, not a zombie)
  R4 a tool that arrives by list_changed (readOnlyHint true) is held; the notification reaches the client
  R5 an unhashable tool name is -32602, not an internal error
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

from tests.client import Client


def guard_for(mode, reads, root):
    path = os.path.join(root, "reads.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"server": "up", "reads": reads}, fh)
    argv = [sys.executable, "-m", "oathline_guard", "run", "--server", "up", "--reads", path, "--home", os.path.join(root, "home"),
            "--", sys.executable, "-m", "tests.fake_upstreams", mode]
    return Client(argv, extra_env={"FAKE_LOG": os.path.join(root, "upstream.log")})


class ReviewCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="oathline-guard-r-")
        self.addCleanup(shutil.rmtree, self.root, True)

    def guard(self, mode, reads):
        g = guard_for(mode, reads, self.root)
        self.addCleanup(g.close)
        return g

    def upstream_log(self):
        p = os.path.join(self.root, "upstream.log")
        if not os.path.exists(p):
            return []
        with open(p, encoding="utf-8") as fh:
            return [json.loads(ln) for ln in fh if ln.strip()]


class R1_UpstreamAsks(ReviewCase):
    def test_r1(self):
        g = self.guard("asks", ["read_a"])
        g.start()
        self.assertEqual({t["name"] for t in g.tools()}, {"read_a", "read_b", "write_b"})
        answers = [e["answer_to_our_request"] for e in self.upstream_log() if "answer_to_our_request" in e]
        self.assertTrue(answers, "the Guard never answered the upstream's request")
        self.assertEqual(answers[0]["id"], "up-1")
        self.assertEqual(answers[0]["error"]["code"], -32601)


class R2_Pagination(ReviewCase):
    def test_r2(self):
        g = self.guard("pages", ["read_a", "read_b"])
        g.start()
        page1 = g.call("tools/list")["result"]
        self.assertEqual([t["name"] for t in page1["tools"]], ["read_a"])
        self.assertEqual(page1["nextCursor"], "p2")
        page2 = g.call("tools/list", {"cursor": "p2"})["result"]
        self.assertEqual([t["name"] for t in page2["tools"]], ["read_b", "write_b"])
        self.assertFalse(g.tool("read_b")["result"]["isError"])              # a listed read on page 2 passes
        held = g.tool("write_b")["result"]
        self.assertTrue(held["isError"])
        self.assertIn("Not run", held["content"][0]["text"])
        self.assertNotIn({"call": "write_b"}, self.upstream_log())


class R3_UpstreamDies(ReviewCase):
    def test_r3(self):
        g = self.guard("dies", ["read_a"])
        g.start()
        r = g.tool("read_a")
        self.assertIn("error", r)
        self.assertEqual(g.p.wait(timeout=15), 1)                            # the Guard exits: the client can restart it


class R4_ListChanged(ReviewCase):
    def test_r4(self):
        g = self.guard("grows", ["read_a"])
        g.start()
        g.tool("read_a")                                                     # the upstream grows a tool and says so
        self.assertIn("new_tool", {t["name"] for t in g.tools()})            # (a round trip: the notification has arrived by now)
        self.assertIn("notifications/tools/list_changed", [n.get("method") for n in g.notifications])
        r = g.tool("new_tool")["result"]
        self.assertTrue(r["isError"])
        self.assertIn("Not run", r["content"][0]["text"])
        self.assertNotIn({"call": "new_tool"}, self.upstream_log())


class R4b_AsItArrives(ReviewCase):
    """FABLE 17:30: 'as it arrives' tested for real. The upstream sends list_changed AFTER its answer; the client then sends nothing,
    and must still receive the notification (a Guard that hands notifications on only at its next upstream call is red here).
    The 'early' mode (notification before the answer) is kept too: it must reach the client by the time the answer does."""

    def test_r4b_after_the_answer_with_no_further_request(self):
        g = self.guard("grows", ["read_a"])
        g.start()
        g.tool("read_a")
        self.assertTrue(g.wait_notification("notifications/tools/list_changed", timeout=5))

    def test_r4c_before_the_answer(self):
        g = self.guard("early", ["read_a"])
        g.start()
        g.tool("read_a")
        self.assertIn("notifications/tools/list_changed", [n.get("method") for n in g.notifications])


class R3a_UpstreamGoesMute(ReviewCase):
    def test_r3a_closed_output_alive_process(self):
        g = self.guard("mute", ["read_a"])
        g.start()
        self.assertIn("error", g.tool("read_a"))
        self.assertEqual(g.p.wait(timeout=15), 1)            # not a zombie: the upstream's output is gone, the Guard exits


class R3b_UpstreamDiesIdle(ReviewCase):
    def test_r3b_idle_death_is_noticed_without_a_call(self):
        g = self.guard("idle", ["read_a"])
        g.start()
        g.tools()
        self.assertEqual(g.p.wait(timeout=15), 1)            # nothing sent after the upstream died: the Guard exits on its own


class R6_NotificationBeforeInitialize(ReviewCase):
    def test_r6_the_initialize_answer_comes_first(self):
        g = self.guard("chatty", ["read_a"])
        r = g.start()                                         # whatever the upstream sent before, the first line is the answer
        self.assertIn("result", r)
        self.assertEqual(g.notifications, [])                # held back until the client's initialize was answered
        g.tools()                                             # then handed on
        self.assertIn("notifications/message", [n.get("method") for n in g.notifications])


class R5_BadName(ReviewCase):
    def test_r5(self):
        g = self.guard("pages", ["read_a"])
        g.start()
        self.assertEqual(g.call("tools/call", {"name": ["x"], "arguments": {}})["error"]["code"], -32602)


if __name__ == "__main__":
    unittest.main()
