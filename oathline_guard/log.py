"""`oathline-guard log`: read one server's Core record from where you stopped (0.2.0; Core 0.3.0's `events(since_seq)`).

    oathline-guard log --server NAME [--home DIR] [--since N] [--verify]

Prints the server's Core audit events after event N as JSON lines (every event carries `seq` inside its hashed body, so a reader
keeps the last `seq` it read and asks for what came after). With --verify it also prints Core's verify report for the same range
(event N and every later link; from the first event without --since) and exits 1 when it does not hold. Read-only: the record is
opened for reading and never created or written. Exit 2 when the server has no record.
"""
from __future__ import annotations

import argparse
import json
import os
import re

from oathline import AuditLog

SERVER_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="oathline-guard log")
    ap.add_argument("--server", required=True)
    ap.add_argument("--home", default=os.path.join(os.path.expanduser("~"), ".oathline-guard"))
    ap.add_argument("--since", type=int, default=None, help="only events with seq greater than this")
    ap.add_argument("--verify", action="store_true", help="also check the hash chain for the same range")
    a = ap.parse_args(argv)
    if not SERVER_RX.match(a.server) or ".." in a.server:
        print(json.dumps({"ok": False, "error": "not a server name"}))
        return 2
    path = os.path.join(a.home, a.server, "audit.db")
    if not os.path.isfile(path):
        print(json.dumps({"ok": False, "error": f"no record for server {a.server!r} under {a.home}"}))
        return 2
    log = AuditLog(path, chain_id=f"oathline-guard-{a.server}", read_only=True)
    try:
        for e in log.events(since_seq=a.since):
            print(json.dumps(e, sort_keys=True, ensure_ascii=False))
        if not a.verify:
            return 0
        r = log.verify(from_seq=a.since) if a.since is not None else log.verify()
        print(json.dumps(r, sort_keys=True))
        return 0 if r.get("ok") else 1
    finally:
        log.close()
