"""The Guard process (OATHLINE_GUARD_PLAN sections 2, 3): an MCP server to the client, an MCP client to the real server it starts.

    python -m oathline_guard run --server NAME [--reads READS.json] [--home DIR] -- <the real server's command ...>

Reads (the OPERATOR's list, never the upstream's readOnlyHint, never the agent) pass to the upstream untouched. Every other tool is
held: in G2 it is simply not run; from G3 it becomes a heard proposal. No read list = nothing passes. stdout carries JSON-RPC only.

The upstream is read by its own thread (FABLE 16:58 review): a request FROM the upstream (roots/list, sampling, elicitation) is
answered -32601 at once, never left to deadlock the Guard; a notification is handed to the client as it arrives; a response goes to
the one call waiting for it. When the upstream's output ends (it died, it closed its stdout while alive, or it wrote what cannot be read), the Guard answers any
call in flight with the error, kills it and exits 1 within about a second, even with no call in flight, so the client can restart it.
Limit until G5: no timeout on an upstream call (a hung upstream hangs the serial loop, ping included).
"""
from __future__ import annotations

import io
import json
import os
import queue
import shutil
import subprocess
import sys
import threading

from . import __version__, stdio

PENDING_MAX = 1000                                                      # upstream notifications held before the client's first answer
PASS_METHODS = {"resources/list": "resources", "resources/read": "resources", "resources/templates/list": "resources",
                "prompts/list": "prompts", "prompts/get": "prompts"}   # reads (plan section 3), passed only if the upstream offers them


class UpstreamError(Exception):
    pass


class Upstream:
    """The real MCP server, spawned with its own command; spoken to over its stdio (LF only, UTF-8), read by its own thread."""

    def __init__(self, argv: list[str], on_notification=None, on_end=None):
        if not argv:
            raise UpstreamError("no upstream command after --")
        exe = shutil.which(argv[0]) or argv[0]               # FABLE 16:58 nit: `npx` and friends on Windows
        self.p = subprocess.Popen([exe, *argv[1:]], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None)
        self.stdin = io.TextIOWrapper(self.p.stdin, encoding="utf-8", newline="\n", write_through=True)   # LF only, never CRLF
        # errors="replace" (FABLE 18:00): a stray undecodable byte makes its line a parse error that _read skips, not the end of
        # the upstream; valid JSON carrying U+FFFD still parses
        self.stdout = io.TextIOWrapper(self.p.stdout, encoding="utf-8", errors="replace", newline="\n")
        self.lock = threading.Lock()
        self.responses: queue.Queue = queue.Queue()
        self.on_notification = on_notification or (lambda msg: None)
        self.on_end = on_end or (lambda: None)
        self.ended = threading.Event()
        self.n = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _send(self, msg) -> None:
        with self.lock:
            stdio.write(self.stdin, msg)

    def _read(self) -> None:
        try:
            while True:
                got = stdio.read(self.stdout)
                if got is None:
                    break
                if not isinstance(got, dict):
                    continue
                if "method" in got and "id" in got:          # the upstream asks US something: refused at once, never left hanging
                    try:
                        self._send(stdio.error(got["id"], -32601, f"{got['method']} is not supported by oathline-guard v1"))
                    except (OSError, ValueError):
                        break
                elif "method" in got:
                    self.on_notification(got)
                elif "id" in got:
                    self.responses.put(got)
        except (OSError, ValueError):                       # incl. UnicodeDecodeError: an upstream we cannot read is ended too
            pass
        self.ended.set()
        self.responses.put(None)                              # the upstream closed its output
        self.on_end()

    def call(self, method: str, params=None) -> dict:
        self.n += 1
        mid = f"g{self.n}"
        msg = {"jsonrpc": "2.0", "id": mid, "method": method}
        if params is not None:
            msg["params"] = params
        try:
            self._send(msg)
        except (OSError, ValueError) as exc:
            raise UpstreamError(f"the upstream server is not running ({exc})") from None
        while True:
            got = self.responses.get()
            if got is None:
                self.responses.put(None)                      # every later call sees the end too
                raise UpstreamError("the upstream server closed its output")
            if got.get("id") == mid:
                return got
            # a response to an id we no longer wait for: dropped

    def notify(self, method: str, params=None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})})

    def kill(self) -> None:
        try:
            self.p.kill()
        except Exception:  # noqa: BLE001
            pass

    def dead(self) -> bool:
        try:
            self.p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            return False
        return True

    def close(self) -> None:
        try:
            self.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.p.wait(timeout=5)
        except Exception:  # noqa: BLE001
            self.p.kill()


def load_reads(path: str | None, server: str) -> frozenset:
    """The operator's read list (plan section 3). Missing, unreadable or for another server: nothing is a read (fail closed)."""
    if not path:
        return frozenset()
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"oathline-guard: read list {path} unreadable ({exc}): nothing passes", file=sys.stderr)
        return frozenset()
    if not isinstance(d, dict) or d.get("server") != server or not isinstance(d.get("reads"), list):
        print(f"oathline-guard: read list {path} is not for server {server!r}: nothing passes", file=sys.stderr)
        return frozenset()
    return frozenset(str(x) for x in d["reads"] if isinstance(x, str))


class Guard:
    def __init__(self, server: str, upstream_argv: list[str], reads: frozenset, home: str, stdout=None):
        self.server, self.reads, self.home = server, reads, home
        self.out = stdout or sys.stdout
        self.out_lock = threading.Lock()
        os.makedirs(home, exist_ok=True)
        # tool_names is rebound by the reader thread (list_changed) and added to by the main thread WITHOUT a lock, on purpose: every
        # interleaving is fail-closed or self-healing (an unknown name triggers a full refresh before anything is forwarded).
        self.tool_names: set = set()
        self.client_initialized = False
        self.closing = False
        self.pending_notes: list[dict] = []                     # upstream notifications held until the client's FIRST answer
        self.dropped_notes = 0
        self.up = Upstream(upstream_argv, on_notification=self._upstream_notification, on_end=self._upstream_ended)
        try:
            init = self.up.call("initialize", {"protocolVersion": stdio.PROTOCOL_VERSIONS[0], "capabilities": {},
                                              "clientInfo": {"name": "oathline-guard", "version": __version__}})
            if "result" not in init:
                raise UpstreamError(f"the upstream server refused initialize: {init.get('error')}")
            self.upstream_info = init["result"].get("serverInfo", {})
            self.upstream_caps = init["result"].get("capabilities") or {}
            self.up.notify("notifications/initialized")
            self.refresh_tools()
        except BaseException:
            self.up.close()                                   # FABLE 17:30 / 18:00 nits: never left running after a failed start
            raise

    # ---------------------------------------------------------------- the upstream's side
    def _write(self, msg) -> None:
        with self.out_lock:
            stdio.write(self.out, msg)

    def _upstream_notification(self, msg: dict) -> None:
        if msg.get("method") == "notifications/tools/list_changed":
            self.tool_names = set()                               # learnt again on next use; a new tool is held: not on the read list
        with self.out_lock:
            if not self.client_initialized:                       # FABLE 17:30 nit: the client's first answer is its first line
                if len(self.pending_notes) >= PENDING_MAX:        # FABLE 18:00 nit: bounded; the oldest goes, said once on stderr
                    self.pending_notes.pop(0)
                    if not self.dropped_notes:
                        print(f"oathline-guard: more than {PENDING_MAX} upstream notifications before the client's first answer; "
                              "dropping the oldest", file=sys.stderr)
                    self.dropped_notes += 1
                self.pending_notes.append(msg)
                return
            stdio.write(self.out, msg)

    def _upstream_ended(self) -> None:
        """The upstream's output ended (it died, or closed its stdout, or wrote what we cannot read): it can never answer again. An
        in-flight call answers its error first; then the Guard exits so the client can restart it (FABLE 17:30, R3 residuals)."""
        def finish():
            import time as _t
            _t.sleep(1.0)                                         # let a call that was waiting write its error line
            if self.closing:                                      # a normal shutdown closed the upstream: not a failure
                return
            self.up.kill()
            print("oathline-guard: the upstream server's output ended; exiting", file=sys.stderr)
            try:
                with self.out_lock:
                    self.out.flush()
            except Exception:  # noqa: BLE001
                pass
            os._exit(1)
        threading.Thread(target=finish, daemon=True).start()

    def refresh_tools(self) -> None:
        """Every page of the upstream's tools (the Guard must know them all to say "unknown tool" truthfully)."""
        names, cursor, pages = set(), None, 0
        while pages < 100:
            r = self.up.call("tools/list", {"cursor": cursor} if cursor else None)
            res = r.get("result") or {}
            names |= {t.get("name") for t in res.get("tools") or [] if isinstance(t, dict)}
            cursor, pages = res.get("nextCursor"), pages + 1
            if not cursor:
                break
        self.tool_names = names

    def capability(self, tool: str) -> str:
        return f"mcp/{self.server}/{tool}"

    # ---------------------------------------------------------------- the client's side
    def handle(self, msg) -> dict | None:
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
            return stdio.error(msg.get("id") if isinstance(msg, dict) else None, -32600, "invalid request")
        if "id" not in msg:
            return None                                          # notifications from the client: nothing to answer
        mid, method, params = msg["id"], msg["method"], msg.get("params") or {}
        if method == "initialize":
            caps = {"tools": {"listChanged": True}}
            for kind in ("resources", "prompts"):                # mirrored: offered only when the upstream offers them
                if kind in self.upstream_caps:
                    caps[kind] = {}
            return stdio.result(mid, {
                "protocolVersion": stdio.agreed_version(params.get("protocolVersion") if isinstance(params, dict) else None),
                "capabilities": caps,
                "serverInfo": {"name": "oathline-guard", "version": __version__},
                "instructions": (f"oathline-guard in front of {self.server!r} ({self.upstream_info.get('name', '?')}). Reads pass. Every "
                                 "other tool is held for a person's yes on a channel you do not control; you cannot give that yes.")})
        if method == "ping":
            return stdio.result(mid, {})
        if method == "tools/list":                               # passed through: the client's params, the upstream's result
            r = self.up.call("tools/list", params or None)
            r["id"] = mid
            for t in (r.get("result") or {}).get("tools") or []:
                if isinstance(t, dict):
                    self.tool_names.add(t.get("name"))
            return r
        if method == "tools/call":
            return self.tools_call(mid, params if isinstance(params, dict) else {})
        if method in PASS_METHODS and PASS_METHODS[method] in self.upstream_caps:
            r = self.up.call(method, params)
            r["id"] = mid
            return r
        return stdio.error(mid, -32601, f"{method} is not passed by oathline-guard v1")

    def tools_call(self, mid, params: dict) -> dict:
        name = params.get("name")
        if not isinstance(name, str):                            # FABLE 16:58 nit: -32602, not an internal error
            return stdio.error(mid, -32602, "the tool name must be a string")
        if name not in self.tool_names:
            self.refresh_tools()
            if name not in self.tool_names:
                return stdio.error(mid, -32602, f"unknown tool: {name!r}")
        if name in self.reads:                                   # the operator's read list: passed, the upstream's own answer
            r = self.up.call("tools/call", {"name": name, "arguments": params.get("arguments") or {}})
            r["id"] = mid
            return r
        return stdio.result(mid, self.held(name, params.get("arguments") or {}))

    def held(self, name: str, arguments: dict) -> dict:
        """G2: a gated tool is not run. (G3 makes it a heard proposal.)"""
        return stdio.text_result(f"Not run: {self.server}/{name} is held by oathline-guard for a person's yes, and this build has no "
                                 "channel to ask on yet. Nothing was sent to the server.", is_error=True)

    def serve(self, stdin=sys.stdin) -> int:
        while True:
            msg = stdio.read(stdin)
            if msg is None:
                return 0
            if msg == "<parse error>":
                self._write(stdio.error(None, -32700, "parse error"))
                continue
            try:
                resp = self.handle(msg)
            except UpstreamError as exc:
                self._write(stdio.error(msg.get("id") if isinstance(msg, dict) else None, -32603, f"upstream: {exc}"))
                if self.up.ended.is_set() or self.up.dead():   # output gone (dead, or alive but mute: FABLE 17:30): never usable again
                    self.up.kill()
                    print("oathline-guard: the upstream server can no longer answer; exiting", file=sys.stderr)
                    return 1
                continue
            except Exception as exc:  # noqa: BLE001 - never die on one message
                resp = stdio.error(msg.get("id") if isinstance(msg, dict) else None, -32603, f"internal error: {type(exc).__name__}")
            if resp is not None:
                self._write(resp)
            if resp is not None and not self.client_initialized:  # the FIRST answer is out (initialize, or a ping first: FABLE 18:00)
                with self.out_lock:                               # the answer is out: now the held notifications
                    self.client_initialized = True
                    for note in self.pending_notes:
                        stdio.write(self.out, note)
                    self.pending_notes.clear()


def run(argv: list[str]) -> int:
    import argparse
    if "--" not in argv:
        print("oathline-guard run: put the real server's command after --", file=sys.stderr)
        return 2
    i = argv.index("--")
    ours, upstream_argv = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser(prog="oathline-guard run")
    ap.add_argument("--server", required=True)
    ap.add_argument("--reads")
    ap.add_argument("--home", default=os.path.join(os.path.expanduser("~"), ".oathline-guard"))
    a = ap.parse_args(ours)
    try:
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    reads = load_reads(a.reads, a.server)
    guard = None
    try:
        guard = Guard(a.server, upstream_argv, reads, os.path.join(a.home, a.server))
        return guard.serve()
    except (UpstreamError, OSError) as exc:
        print(f"oathline-guard: {exc}", file=sys.stderr)
        return 2
    finally:
        if guard is not None:
            guard.closing = True
            guard.up.close()
