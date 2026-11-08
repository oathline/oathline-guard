"""G0 (OATHLINE_GUARD_PLAN section 10): the demo server `fake-db-mcp` and the scripted client, with NO Guard in between.

fake-db-mcp is a tiny stdio MCP server whose state lives in one JSON file: databases with tables and backups. Two reads
(list_databases, list_tables) and two writes (drop_database, delete_backups). It is the PocketOS scene in miniature: called directly,
nothing stops `drop_database("prod")` and `delete_backups("prod")`; that is what the Guard is for (G2-G4)."""
import json
import os
import shutil
import tempfile
import unittest

from tests.client import Client, fake_db_argv


class G0(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="oathline-guard-g0-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.state = os.path.join(self.root, "db.json")
        self.c = Client(fake_db_argv(self.state))
        self.addCleanup(self.c.close)

    def db(self):
        with open(self.state, encoding="utf-8") as fh:
            return json.load(fh)

    def text(self, r):
        return r["result"]["content"][0]["text"]

    def test_g0a_the_server_answers_initialize_and_lists_four_tools(self):
        r = self.c.start()["result"]
        self.assertEqual(r["serverInfo"]["name"], "fake-db-mcp")
        tools = {t["name"]: t for t in self.c.tools()}
        self.assertEqual(set(tools), {"list_databases", "list_tables", "drop_database", "delete_backups"})
        self.assertTrue(tools["list_tables"]["annotations"]["readOnlyHint"])
        self.assertTrue(tools["drop_database"]["annotations"]["destructiveHint"])

    def test_g0b_a_fresh_state_has_prod_and_staging_with_backups(self):
        self.c.start()
        self.assertEqual(json.loads(self.text(self.c.tool("list_databases"))), ["prod", "staging"])
        self.assertIn("users", json.loads(self.text(self.c.tool("list_tables", {"database": "prod"}))))
        self.assertEqual(self.db()["prod"]["backups"], ["prod-2026-11-07", "prod-2026-11-08"])

    def test_g0c_called_directly_nothing_stops_the_delete(self):
        self.c.start()
        self.assertFalse(self.c.tool("delete_backups", {"name": "prod"})["result"]["isError"])   # the backups first, then the database
        self.assertFalse(self.c.tool("drop_database", {"name": "prod"})["result"]["isError"])
        self.assertNotIn("prod", self.db())                       # gone, with its backups: the incident, without a Guard

    def test_g0d_errors(self):
        self.c.start()
        r = self.c.tool("drop_database", {"name": "nope"})["result"]
        self.assertTrue(r["isError"])
        self.assertIn("no database", r["content"][0]["text"])
        self.assertEqual(self.c.tool("format_disk", {})["error"]["code"], -32602)
        self.assertEqual(self.c.call("resources/list")["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
