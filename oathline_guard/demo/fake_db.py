"""fake-db-mcp: the demo MCP server of the PocketOS quickstart (OATHLINE_GUARD_PLAN section 9). Its whole state is one JSON file:
databases, each with tables and backups. Two reads and two writes; no guard of its own (that is the point).

    python -m oathline_guard.demo.fake_db --state PATH
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .. import stdio

FRESH = {"prod": {"tables": ["users", "orders", "invoices"], "backups": ["prod-2026-11-07", "prod-2026-11-08"]},
         "staging": {"tables": ["users", "orders"], "backups": ["staging-2026-11-08"]}}


def _schema(props=None, required=()):
    return {"type": "object", "properties": props or {}, "required": list(required), "additionalProperties": False}


_NAME = {"type": "string", "description": "a database name"}
TOOLS = [
    {"name": "list_databases", "description": "List the databases.", "inputSchema": _schema(),
     "annotations": {"readOnlyHint": True}},
    {"name": "list_tables", "description": "List the tables of a database.", "inputSchema": _schema({"database": _NAME}, ["database"]),
     "annotations": {"readOnlyHint": True}},
    {"name": "drop_database", "description": "Tidy up an unused database.",            # the description is the server's own words
     "inputSchema": _schema({"name": _NAME}, ["name"]), "annotations": {"readOnlyHint": False, "destructiveHint": True}},
    {"name": "delete_backups", "description": "Free space by removing old backups.",
     "inputSchema": _schema({"name": _NAME}, ["name"]), "annotations": {"readOnlyHint": False, "destructiveHint": True}},
]


class Db:
    def __init__(self, path):
        self.path = path
        if not os.path.exists(path):
            self.save(json.loads(json.dumps(FRESH)))

    def load(self):
        with open(self.path, encoding="utf-8") as fh:
            return json.load(fh)

    def save(self, state):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=1)
        os.replace(tmp, self.path)

    def call(self, name, args):
        s = self.load()
        if name == "list_databases":
            return json.dumps(sorted(s)), False
        db = str(args.get("database") or args.get("name") or "")
        if db not in s:
            return f"no database {db!r}", True
        if name == "list_tables":
            return json.dumps(s[db]["tables"]), False
        if name == "drop_database":
            del s[db]
            self.save(s)
            return f"dropped {db}", False
        if name == "delete_backups":
            n = len(s[db]["backups"])
            s[db]["backups"] = []
            self.save(s)
            return f"deleted {n} backups of {db}", False
        return f"unknown tool {name}", True


def serve(db: Db, stdin=sys.stdin, stdout=sys.stdout) -> int:
    names = {t["name"] for t in TOOLS}
    while True:
        msg = stdio.read(stdin)
        if msg is None:
            return 0
        if msg == "<parse error>":
            stdio.write(stdout, stdio.error(None, -32700, "parse error"))
            continue
        if not isinstance(msg, dict) or "id" not in msg:
            continue
        mid, method, params = msg["id"], msg.get("method"), msg.get("params") or {}
        if method == "initialize":
            stdio.write(stdout, stdio.result(mid, {"protocolVersion": stdio.agreed_version(params.get("protocolVersion")),
                                                   "capabilities": {"tools": {"listChanged": False}},
                                                   "serverInfo": {"name": "fake-db-mcp", "version": "0.1"}}))
        elif method == "ping":
            stdio.write(stdout, stdio.result(mid, {}))
        elif method == "tools/list":
            stdio.write(stdout, stdio.result(mid, {"tools": TOOLS}))
        elif method == "tools/call":
            name = params.get("name")
            if name not in names:
                stdio.write(stdout, stdio.error(mid, -32602, f"unknown tool: {name}"))
                continue
            text, is_error = db.call(name, params.get("arguments") or {})
            stdio.write(stdout, stdio.result(mid, stdio.text_result(text, is_error=is_error)))
        else:
            stdio.write(stdout, stdio.error(mid, -32601, f"method not found: {method}"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fake-db-mcp")
    ap.add_argument("--state", required=True)
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return serve(Db(a.state))


if __name__ == "__main__":
    sys.exit(main())
