"""The guarded server's Registry for a READER: the oathline-agent CLI's `--registry` hook.

    OATHLINE_GUARD_SERVER=db [OATHLINE_GUARD_HOME=~/.oathline-guard] \\
        oathline-agent --audit <home>/db/audit.db --tokens <home>/db/tokens.db --registry oathline_guard.registry:for_server unheard

It opens the Guard's own guard.db READ-ONLY (SQLite mode=ro; a reader never writes) and builds the same Registry the Guard and the
approve window build (record.build_registry), so `unheard` judges the record by the capabilities that are heard now.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from .record import build_registry


def for_server():
    server = os.environ.get("OATHLINE_GUARD_SERVER") or ""
    home = os.environ.get("OATHLINE_GUARD_HOME") or os.path.join(os.path.expanduser("~"), ".oathline-guard")
    if not server:
        raise ValueError("set OATHLINE_GUARD_SERVER to the guarded server's name")
    path = Path(home) / server / "guard.db"
    if not path.is_file():
        raise ValueError(f"no guard record at {path}")
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        caps = [(c, t, json.loads(k)) for c, t, k in db.execute("SELECT capability, tool, keys FROM caps")]
        row = db.execute("SELECT value FROM meta WHERE key='human'").fetchone()
    finally:
        db.close()
    return build_registry(server, caps, row[0] if row else "")
