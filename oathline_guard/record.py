"""The Guard's record (OATHLINE_GUARD_PLAN sections 4, 5, 7 as amended after FABLE 15:47): Core 0.2.0's two files (the audit chain and the
token store) plus the Guard's own table (guard.db), in ~/.oathline-guard/<server>/.

Two sides use it, never the same functions:
  the Guard process  propose(), the retry match, confirm_from_yes() (Core's confirm and the executor: only this process holds the pipe)
  the human side     text(), show() (the re-hash first), hear(), yes(), no(): what `oathline-guard approve` wraps (G4). It never
                     calls confirm() and never builds an executor.

The words are the Guard's, never the agent's and never the server's description. A single-line value is shown as itself when it is a
plain string (printable, no edge spaces) and otherwise as its JSON literal, so a value can never write a line of its own. A long or
multi-line value is carried in Core by its hash, {"sha256", "chars"}, with a short `said`, and shown WHOLE as a block whose every line
starts with "| " (a gate line never does), closed by "--- end of <key> ---"; the human side re-hashes the block before Core's show().
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import time

from oathline import AuditLog, Capability, Engine, Registry, TokenStore

PRODUCT = "oathline-guard"           # the product actor that shows and hears (Core's non-human list matches whole names; not on it)
AGENT = "agent"                      # the proposing principal: on Core's non-human list, it can never confirm
TTL_SECONDS = 900                    # a proposal lives 15 minutes (plan section 6)
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
LONG_CHARS = 200                     # a string longer than this is a block
ITEMS_BUDGET = 7000                  # Core's items cap is 8 KB (value + said count): carry the largest by hash until the rest fit
SHOWN_TEXT_MAX = 16000               # Core shows at most 16,384 characters; a call whose text would be longer is refused at proposal
GUTTER = "| "
END_MARK = "--- end of {key} ---"
KEY_RX = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
RESERVED = ("code", "tool", "_call")


def _json(v) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def canonical(arguments) -> dict:
    return json.loads(_json(dict(arguments or {})))


def _text(v) -> str:
    return v if isinstance(v, str) else _json(v)


def _plain(v) -> bool:
    return isinstance(v, str) and v != "" and v == v.strip() and all(ch.isprintable() for ch in v)


def one_line(v) -> str:
    """A value's words on one line: a plain string as itself, anything else as its JSON literal (newlines and controls escaped)."""
    if _plain(v):
        return v
    return json.dumps(v, sort_keys=True, ensure_ascii=False) if not isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def _carried(v) -> bool:
    return isinstance(v, dict) and set(v) == {"sha256", "chars"}


class Record:
    def __init__(self, folder: str, server: str, *, human: str | None = None, clock=time.time):
        os.makedirs(folder, exist_ok=True)
        self.folder, self.server, self.human, self.clock = folder, server, human, clock
        self.db = sqlite3.connect(os.path.join(folder, "guard.db"), isolation_level=None, timeout=5)
        self.db.execute("CREATE TABLE IF NOT EXISTS caps (capability TEXT PRIMARY KEY, tool TEXT NOT NULL, keys TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS calls (call TEXT PRIMARY KEY, tool TEXT NOT NULL, token TEXT NOT NULL, code TEXT NOT NULL,"
                        " arguments TEXT NOT NULL, args_hash TEXT NOT NULL, status TEXT NOT NULL, outcome TEXT, delivered INTEGER NOT NULL"
                        " DEFAULT 0, created REAL NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS answers (call TEXT PRIMARY KEY, kind TEXT NOT NULL, code_typed TEXT, human TEXT NOT NULL,"
                        " at REAL NOT NULL)")
        self._engine = None
        self._executor = None
        self._renderer_caps: set = set()

    # ---------------------------------------------------------------- capabilities (written by the Guard at start, read by both sides)
    def capability(self, tool: str) -> str:
        return f"mcp/{self.server}/{tool}"

    def declare_tools(self, tools: list[dict], gated: set) -> None:
        """The Guard, at start: one Core capability per gated tool; its argument keys (from the tool's own schema) may be blocks."""
        for t in tools:
            name = t.get("name")
            if name not in gated:
                continue
            props = sorted(((t.get("inputSchema") or {}).get("properties") or {}).keys())
            self.db.execute("INSERT OR REPLACE INTO caps (capability, tool, keys) VALUES (?,?,?)", (self.capability(name), name, _json(props)))
        self._engine = None

    def _caps(self) -> list[tuple]:
        return [(c, t, json.loads(k)) for c, t, k in self.db.execute("SELECT capability, tool, keys FROM caps")]

    def engine(self, human: str | None = None) -> Engine:
        human = human or self.human or ""
        if self._engine is None:
            caps = [Capability(c, frozenset({AGENT, human}) if human else frozenset({AGENT}), writes=True, needs_confirmation=True,
                               approvers=frozenset({human}) if human else frozenset(), heard=True, products=frozenset({PRODUCT}),
                               screen_keys=frozenset(keys), description=f"the MCP tool {tool} on {self.server}, run once after a heard yes")
                    for c, tool, keys in self._caps()]
            eng = Engine(Registry(caps), audit=AuditLog(os.path.join(self.folder, "audit.db"), chain_id=f"oathline-guard-{self.server}"),
                         tokens=TokenStore(os.path.join(self.folder, "tokens.db"), ttl_seconds=TTL_SECONDS),
                         humans=frozenset({human}) if human else None, approver_check=self._approver_check)
            for c, tool, keys in self._caps():
                eng.register_renderer(c, self._render)
                if self._executor is not None:
                    eng.register(c, self._executor)
            self._engine = eng
        return self._engine

    def set_executor(self, fn) -> None:
        """The Guard process only: fn(tool, arguments) -> result, raising on an upstream error. Never set on the human side."""
        self._executor = self._wrap_executor(fn)
        self._engine = None

    # ---------------------------------------------------------------- the words
    @staticmethod
    def _render(key: str, value) -> str:
        if _carried(value):
            return f"{value['chars']} characters, sha256 {value['sha256'][:16]}"
        return one_line(value)

    def _is_block(self, value) -> bool:
        return isinstance(value, str) and (len(value) > LONG_CHARS or "\n" in value or "\r" in value)

    def _plan(self, args: dict, keys: list) -> tuple[dict, list] | str:
        """Core's arguments and items for these arguments, or the reason they cannot be shown."""
        for k in args:
            if not KEY_RX.match(k) or k in RESERVED:
                return f"bad_argument_key: {k!r}"
        blocks = {k for k, v in args.items() if self._is_block(v)}
        def size(k):
            v = args[k]
            return 0 if k in blocks else 2 * len(_text(v).encode("utf-8")) + len(k) + 16
        for k in sorted(args, key=size, reverse=True):         # the largest first, until the items fit the budget
            if sum(size(x) for x in args) <= ITEMS_BUDGET:
                break
            blocks.add(k)
        for k in blocks:
            if k not in keys:
                return f"showing_not_declared: {k!r} is long and the tool's schema does not name it"
        core_args, items = {}, []
        for k in sorted(args):
            v = args[k]
            if k in blocks:
                carried = {"sha256": _sha(_text(v)), "chars": len(_text(v))}
                core_args[k] = carried
                items.append({"key": k, "value": carried, "shown_as": "screen", "label": k})
            else:
                core_args[k] = v
                items.append({"key": k, "value": v, "label": k})
        return core_args, items

    def text(self, call: str) -> str:
        """The shown text: built from Core's record and the Guard's stored arguments, never from the call again."""
        row = self._row(call)
        rec = self.engine().tokens.get(row["token"]) or {}
        lines = [f"{self.server} / {row['tool']}"]
        for it in rec.get("items") or []:
            k = it["key"]
            if it.get("shown_as") == "screen":
                lines.append(f"{k}:")
                lines += [GUTTER + ln for ln in _text(row["arguments"][k]).split("\n")]
                lines.append(END_MARK.format(key=k))
            else:
                lines.append(f"{k}: {it.get('said')}")
        lines.append(f"code: {row['code']}")
        return "\n".join(lines)

    @staticmethod
    def block(text: str, key: str) -> str | None:
        lines = str(text or "").split("\n")
        try:
            start = lines.index(f"{key}:")
            end = lines.index(END_MARK.format(key=key), start + 1)
        except ValueError:
            return None
        body = lines[start + 1:end]
        if any(not ln.startswith(GUTTER) for ln in body):
            return None
        return "\n".join(ln[len(GUTTER):] for ln in body)

    # ---------------------------------------------------------------- the Guard process: proposals
    def _row(self, call: str) -> dict:
        r = self.db.execute("SELECT call, tool, token, code, arguments, args_hash, status, outcome, delivered, created FROM calls WHERE call=?",
                            (str(call),)).fetchone()
        if r is None:
            raise KeyError(f"no call {call}")
        return {"call": r[0], "tool": r[1], "token": r[2], "code": r[3], "arguments": json.loads(r[4]), "args_hash": r[5],
                "status": r[6], "outcome": json.loads(r[7]) if r[7] else None, "delivered": bool(r[8]), "created": r[9]}

    def code(self, call: str) -> str:
        return self._row(call)["code"]

    def pending(self) -> list[dict]:
        return [self._row(c) for (c,) in self.db.execute("SELECT call FROM calls WHERE status='pending' ORDER BY created")]

    def match(self, tool: str, arguments: dict) -> dict | None:
        """The retry match: an UNRESOLVED call with these exact arguments, or a resolved one whose outcome was not yet delivered."""
        h = _sha(_json([tool, canonical(arguments)]))
        for (c,) in self.db.execute("SELECT call FROM calls WHERE tool=? AND args_hash=? AND (status='pending' OR delivered=0) "
                                    "ORDER BY created DESC", (tool, h)):
            row = self._row(c)
            if row["status"] == "pending" and self._expired(row):
                self._resolve(c, "expired", {"state": "expired"})
                row = self._row(c)
            return row
        return None

    def _expired(self, row) -> bool:
        return self.clock() > row["created"] + TTL_SECONDS

    def propose(self, tool: str, arguments: dict) -> dict:
        args = canonical(arguments)
        caps = {t: keys for c, t, keys in self._caps()}
        if tool not in caps:
            return {"ok": False, "error": "not_declared"}
        planned = self._plan(args, caps[tool])
        if isinstance(planned, str):
            return {"ok": False, "error": planned}
        core_args, items = planned
        call = "c-" + secrets.token_hex(4)
        core_args["_call"] = call                                # the action names its call (part of its integrity; stripped to run)
        prop = self.engine().request(AGENT, self.capability(tool), core_args, items=items)
        if not prop.get("ok") or prop.get("state") != "proposed":
            return {"ok": False, "error": str(prop.get("error") or prop.get("state") or "not_proposed")}
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(4))
        self.db.execute("INSERT INTO calls (call, tool, token, code, arguments, args_hash, status, created) VALUES (?,?,?,?,?,?, 'pending', ?)",
                        (call, tool, prop["token"], code, _json(args), _sha(_json([tool, args])), self.clock()))
        if len(self.text(call)) > SHOWN_TEXT_MAX:
            self._resolve(call, "refused", {"state": "text_too_large"})
            self.db.execute("UPDATE calls SET delivered=1 WHERE call=?", (call,))
            return {"ok": False, "error": f"text_too_large: the call would show more than {SHOWN_TEXT_MAX} characters; split it"}
        return {"ok": True, "call": call, "token": prop["token"]}

    def _resolve(self, call: str, status: str, outcome: dict) -> None:
        self.db.execute("UPDATE calls SET status=?, outcome=? WHERE call=? AND status='pending'", (status, _json(outcome), call))

    def mark_delivered(self, call: str) -> None:
        self.db.execute("UPDATE calls SET delivered=1 WHERE call=?", (call,))

    # ---------------------------------------------------------------- the human side (what `approve` wraps)
    def show(self, call: str, text: str) -> dict:
        """The product's statement of the exact text shown. Every block must hash to its item first (Core checks a block by label only)."""
        row = self._row(call)
        rec = self.engine().tokens.get(row["token"]) or {}
        for it in rec.get("items") or []:
            if it.get("shown_as") == "screen" and _carried(it.get("value")):
                b = self.block(text, it["key"])
                if b is None or _sha(b) != it["value"]["sha256"]:
                    return {"ok": False, "error": "shown_body_differs", "key": it["key"]}
        return self.engine().show(PRODUCT, row["token"], str(text), channel="screen")

    def hear(self, call: str) -> dict:
        return self.engine().hear(PRODUCT, self._row(call)["token"], channel="screen")

    def yes(self, call: str, code_typed: str, human: str) -> None:
        """The person's yes as a ROW (never confirm(): the Guard process confirms from it). The first answer stands."""
        self.db.execute("INSERT OR IGNORE INTO answers (call, kind, code_typed, human, at) VALUES (?, 'yes', ?, ?, ?)",
                        (call, str(code_typed or ""), str(human), self.clock()))

    def no(self, call: str, human: str) -> None:
        """The person's no: a RECORDED outcome; any later yes is too late."""
        self.db.execute("INSERT OR IGNORE INTO answers (call, kind, code_typed, human, at) VALUES (?, 'no', NULL, ?, ?)",
                        (call, str(human), self.clock()))
        self._resolve(call, "refused", {"state": "refused_by_human", "by": str(human)})

    def answer(self, call: str) -> dict | None:
        r = self.db.execute("SELECT kind, code_typed, human, at FROM answers WHERE call=?", (call,)).fetchone()
        return {"kind": r[0], "code_typed": r[1], "human": r[2], "at": r[3]} if r else None

    # ---------------------------------------------------------------- the Guard process: the yes becomes the run
    def _approver_check(self, principal, proof, action) -> bool:
        if not isinstance(proof, dict):
            return False
        try:
            row = self._row(str(proof.get("call") or ""))
        except KeyError:
            return False
        ans = self.answer(row["call"])
        return (row["token"] == (action or {}).get("token") and row["status"] == "pending" and ans is not None and ans["kind"] == "yes"
                and ans["human"] == str(principal) == str(self.human) and ans["code_typed"] == row["code"])

    def _wrap_executor(self, fn):
        def run(core_args: dict):
            """fn(tool, arguments) -> the upstream's result dict; Core gets {"ok": not isError, "upstream": that result}."""
            call = core_args.get("_call")
            row = self._row(call)
            args = {}
            for k, v in core_args.items():
                if k.startswith("_"):
                    continue                                      # Core's and the Guard's own keys, not the tool's
                if _carried(v):
                    full = row["arguments"][k]
                    if _sha(_text(full)) != v["sha256"]:
                        raise ValueError(f"the stored value of {k} does not hash to the proposal")
                    args[k] = full
                else:
                    args[k] = v
            upstream = fn(row["tool"], args)
            return {"ok": not bool((upstream or {}).get("isError")), "upstream": upstream}
        return run

    def confirm_from_yes(self, call: str) -> dict:
        """The Guard process: when a yes row exists, Core's confirm with that row as proof; the executor runs the stored arguments."""
        row = self._row(call)
        ans = self.answer(call)
        if row["status"] != "pending" or ans is None or ans["kind"] != "yes":
            return {"ok": False, "error": "no_yes"}
        res = self.engine().confirm(str(self.human), row["token"], proof={"call": call})
        result = res.get("result") if isinstance(res.get("result"), dict) else {}
        if res.get("state") == "executed":
            self._resolve(call, "ran", {"state": "ran", "upstream": result.get("upstream")})
        elif res.get("state") == "failed":                       # the upstream answered with an error: Core's EXECUTE_FAILED
            self._resolve(call, "failed", {"state": "failed", "upstream": result.get("upstream")})
        elif res.get("error") == "execution_failed":             # the run raised (the upstream died mid-call): EXECUTE_FAILED too
            self._resolve(call, "failed", {"state": "failed", "error": "the upstream server failed during the run"})
        else:
            self._resolve(call, "refused", {"state": "refused", "error": str(res.get("error") or res.get("state"))})
        return res

    def close(self) -> None:
        try:
            if self._engine is not None:
                self._engine.close()
        finally:
            self.db.close()
