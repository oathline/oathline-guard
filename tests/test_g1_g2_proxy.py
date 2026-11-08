"""G1 + G2 (OATHLINE_GUARD_PLAN section 10; in one sitting, so no commit leaves a Guard that forwards writes).

G1, the proxy: the Guard is an MCP server to the client and an MCP client to the real server it starts; tools/list is passed through
unchanged; a read's result is the upstream's, byte for byte; protocol errors come back as errors; stdout carries JSON-RPC only.
G2, the read list: ONLY the operator's read list passes. Every other tool is held: the call never reaches the upstream server and
the agent gets "Not run". An upstream readOnlyHint does not make a tool a read; no read list = nothing passes (fail closed).
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

from tests.client import Client, fake_db_argv


def guard_argv(reads_path, state_path, home, server="db"):
    argv = [sys.executable, "-m", "oathline_guard", "run", "--server", server, "--home", home]
    if reads_path:
        argv += ["--reads", reads_path]
    return argv + ["--"] + fake_db_argv(state_path)


class GuardCase(unittest.TestCase):
    READS = ["list_databases", "list_tables"]

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="oathline-guard-g12-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.state = os.path.join(self.root, "db.json")
        self.home = os.path.join(self.root, "home")
        self.reads = os.path.join(self.root, "reads.json")
        if self.READS is not None:
            with open(self.reads, "w", encoding="utf-8") as fh:
                json.dump({"server": "db", "reads": self.READS}, fh)
        self.g = Client(guard_argv(self.reads if self.READS is not None else None, self.state, self.home))
        self.addCleanup(self.g.close)

    def direct(self):
        c = Client(fake_db_argv(os.path.join(self.root, "direct.json")))
        self.addCleanup(c.close)
        c.start()
        return c

    def db(self):
        with open(self.state, encoding="utf-8") as fh:
            return json.load(fh)


class G1_Proxy(GuardCase):
    def test_g1a_initialize_is_the_guards(self):
        r = self.g.start()["result"]
        self.assertEqual(r["serverInfo"]["name"], "oathline-guard")
        self.assertEqual(set(r["capabilities"]), {"tools"})
        self.assertIn("db", r.get("instructions", ""))

    def test_g1b_tools_list_is_the_upstreams_unchanged(self):
        self.g.start()
        self.assertEqual(self.g.tools(), self.direct().tools())

    def test_g1c_a_read_result_is_the_upstreams(self):
        self.g.start()
        d = self.direct()
        for name, args in (("list_databases", {}), ("list_tables", {"database": "prod"})):
            self.assertEqual(self.g.tool(name, args)["result"], d.tool(name, args)["result"])

    def test_g1d_errors_and_methods(self):
        self.g.start()
        self.assertEqual(self.g.tool("format_disk", {})["error"]["code"], -32602)        # not an upstream tool
        self.assertEqual(self.g.call("sampling/createMessage", {})["error"]["code"], -32601)
        self.assertEqual(self.g.call("resources/subscribe", {"uri": "x"})["error"]["code"], -32601)
        self.assertIn("result", self.g.call("ping"))
        r = self.g.call("resources/list")                                                # a read: passed, the upstream's own answer
        self.assertEqual(r["error"]["code"], -32601)

    def test_g1e_stdout_is_json_rpc_only(self):
        self.g.start()
        self.g.tools()
        self.g.tool("list_databases")
        self.g.tool("drop_database", {"name": "prod"})
        self.g.p.stdin.close()
        rest = self.g.p.stdout.read()
        for line in rest.splitlines():
            if line.strip():
                self.assertEqual(json.loads(line)["jsonrpc"], "2.0")


class G2_ReadList(GuardCase):
    def test_g2a_a_gated_tool_never_reaches_upstream(self):
        self.g.start()
        before = self.db()
        for name in ("drop_database", "delete_backups"):
            r = self.g.tool(name, {"name": "prod"})["result"]
            self.assertTrue(r["isError"], name)
            self.assertIn("Not run", r["content"][0]["text"])
            self.assertIn(f"db/{name}", r["content"][0]["text"])
        self.assertEqual(self.db(), before)                     # prod and its backups untouched

    def test_g2b_the_upstreams_description_is_not_the_guards_words(self):
        self.g.start()
        r = self.g.tool("drop_database", {"name": "prod"})["result"]
        self.assertNotIn("Tidy up", r["content"][0]["text"])

    def test_g2c_reads_pass(self):
        self.g.start()
        self.assertFalse(self.g.tool("list_databases")["result"]["isError"])


class G2_ReadOnlyHintIsNotTrusted(GuardCase):
    READS = ["list_databases"]                                   # list_tables says readOnlyHint, the operator did not list it

    def test_g2d(self):
        self.g.start()
        r = self.g.tool("list_tables", {"database": "prod"})["result"]
        self.assertTrue(r["isError"])
        self.assertIn("Not run", r["content"][0]["text"])


class G2_NoReadList(GuardCase):
    READS = None                                                 # no list at all: nothing is a read

    def test_g2e_fail_closed(self):
        self.g.start()
        r = self.g.tool("list_databases")["result"]
        self.assertTrue(r["isError"])
        self.assertIn("Not run", r["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
