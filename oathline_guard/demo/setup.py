"""`oathline-guard demo`: prepare the quickstart on this machine, then stop.

    oathline-guard demo [--dir DIR] [--human NAME]

It writes DIR/reads.json (the demo server's two reads) and prints the block for claude_desktop_config.json with this machine's
absolute paths: this Python interpreter runs the guard (`-m oathline_guard run ...`) and the demo database server, so the block
does not depend on PATH or on `python` vs `python3`. An existing reads.json is kept. It approves nothing and runs nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

READS = {"server": "db", "reads": ["list_databases", "list_tables"]}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="oathline-guard demo")
    ap.add_argument("--dir", default=os.path.join(os.path.expanduser("~"), "oathline-guard-demo"))
    ap.add_argument("--human", default="you", help="the name of the person who approves (you)")
    a = ap.parse_args(argv)
    folder = os.path.abspath(a.dir)
    os.makedirs(folder, exist_ok=True)
    reads = os.path.join(folder, "reads.json")
    if os.path.exists(reads):
        note = f"kept the existing read list: {reads}"
    else:
        with open(reads, "w", encoding="utf-8") as fh:
            json.dump(READS, fh)
            fh.write("\n")
        note = f"wrote the read list: {reads}"
    py = os.path.abspath(sys.executable)
    block = {"mcpServers": {"db": {"command": py, "args": [
        "-m", "oathline_guard", "run", "--server", "db", "--reads", reads, "--human", a.human,
        "--", py, "-m", "oathline_guard.demo.fake_db", "--state", os.path.join(folder, "db.json")]}}}
    print(note)
    print("\n1. Add this to claude_desktop_config.json (Claude Desktop: Settings > Developer > Edit Config), then restart Claude"
          " Desktop:\n")
    print(json.dumps(block, indent=2))
    print("\n2. In a second terminal, open the approve window and leave it open:\n\n   oathline-guard approve --server db\n\n"
          f"   (or, with nothing needed on PATH: {py} -m oathline_guard approve --server db)\n")
    print('3. Ask Claude: "clean up the old database". The reads run; the drop waits for your code in the approve window.')
    return 0
