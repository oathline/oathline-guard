"""The Guard process (OATHLINE_GUARD_PLAN sections 2, 3): an MCP server to the client, an MCP client to the real server it starts.

    python -m oathline_guard run --server NAME [--reads READS.json] [--home DIR] -- <the real server's command ...>

Reads (the OPERATOR's list, never the upstream's readOnlyHint, never the agent) pass to the upstream untouched. Every other tool is
held: in G2 it is simply not run; from G3 it becomes a heard proposal. No read list = nothing passes. stdout carries JSON-RPC only.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from . import __version__, stdio

PASS_METHODS = ("resources/list", "resources/read", "resources/templates/list", "prompts/list", "prompts/get")   # reads (plan s3)


class UpstreamError(Exception):
    pass


class Upstream:
    """The real MCP server, spawned with its own command; spoken to over its stdio."""

    def __init__(self, argv: list[str]):
        if not argv:
            raise UpstreamError("no upstream command after --")
        self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None, text=True, encoding="utf-8")
        self.n = 0
        self.notifications: list[dict] = []

    def call(self, method: str, params=None) -> dict:
        self.n += 1
        mid = f"g{self.n}"
        msg = {"jsonrpc": "2.0", "id": mid, "method": method}
        if params is not None:
            msg["params"] = params
        try:
            stdio.write(self.p.stdin, msg)
        except (OSError, ValueError) as exc:
            raise UpstreamError(f"the upstream server is not running ({exc})") from None
        while True:
            got = stdio.read(self.p.stdout)
            if got is None:
                raise UpstreamError("the upstream server closed its output")
            if isinstance(got, dict) and got.get("id") == mid:
                return got
            if isinstance(got, dict) and "method" in got and "id" not in got:
                self.notifications.append(got)                 # list_changed, progress, log ...: handed on by the Guard
            # anything else (a stray id, an upstream request to us): ignored in v1

    def notify(self, method: str, params=None) -> None:
        stdio.write(self.p.stdin, {"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})})

    def close(self) -> None:
        try:
            self.p.stdin.close()
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
    def __init__(self, server: str, upstream: Upstream, reads: frozenset, home: str):
        self.server, self.up, self.reads, self.home = server, upstream, reads, home
        os.makedirs(home, exist_ok=True)
        init = self.up.call("initialize", {"protocolVersion": stdio.PROTOCOL_VERSIONS[0], "capabilities": {},
                                          "clientInfo": {"name": "oathline-guard", "version": __version__}})
        if "result" not in init:
            raise UpstreamError(f"the upstream server refused initialize: {init.get('error')}")
        self.upstream_info = init["result"].get("serverInfo", {})
        self.up.notify("notifications/initialized")
        self.refresh_tools()

    def refresh_tools(self) -> None:
        r = self.up.call("tools/list")
        self.tools = (r.get("result") or {}).get("tools") or []
        self.tool_names = {t.get("name") for t in self.tools}

    def capability(self, tool: str) -> str:
        return f"mcp/{self.server}/{tool}"

    # ---------------------------------------------------------------- the client side
    def handle(self, msg) -> dict | None:
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
            return stdio.error(msg.get("id") if isinstance(msg, dict) else None, -32600, "invalid request")
        if "id" not in msg:
            return None                                          # notifications from the client: nothing to answer
        mid, method, params = msg["id"], msg["method"], msg.get("params") or {}
        if method == "initialize":
            return stdio.result(mid, {
                "protocolVersion": stdio.agreed_version(params.get("protocolVersion") if isinstance(params, dict) else None),
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": "oathline-guard", "version": __version__},
                "instructions": (f"oathline-guard in front of {self.server!r} ({self.upstream_info.get('name', '?')}). Reads pass. Every "
                                 "other tool is held for a person's yes on a channel you do not control; you cannot give that yes.")})
        if method == "ping":
            return stdio.result(mid, {})
        if method == "tools/list":
            self.refresh_tools()
            return stdio.result(mid, {"tools": self.tools})      # passed through unchanged (G1)
        if method == "tools/call":
            return self.tools_call(mid, params if isinstance(params, dict) else {})
        if method in PASS_METHODS:
            r = self.up.call(method, params)
            r["id"] = mid
            return r
        return stdio.error(mid, -32601, f"{method} is not passed by oathline-guard v1")

    def tools_call(self, mid, params: dict) -> dict:
        name = params.get("name")
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

    def serve(self, stdin=sys.stdin, stdout=sys.stdout) -> int:
        while True:
            msg = stdio.read(stdin)
            if msg is None:
                return 0
            if msg == "<parse error>":
                stdio.write(stdout, stdio.error(None, -32700, "parse error"))
                continue
            try:
                resp = self.handle(msg)
            except UpstreamError as exc:
                resp = stdio.error(msg.get("id") if isinstance(msg, dict) else None, -32603, f"upstream: {exc}")
            except Exception as exc:  # noqa: BLE001 - never die on one message
                resp = stdio.error(msg.get("id") if isinstance(msg, dict) else None, -32603, f"internal error: {type(exc).__name__}")
            for note in self.up.notifications:                   # the upstream's notifications, handed on after the answer
                if note.get("method") == "notifications/tools/list_changed":
                    self.refresh_tools()                         # a new tool is held by default: it is not on the read list
                stdio.write(stdout, note)
            self.up.notifications.clear()
            if resp is not None:
                stdio.write(stdout, resp)


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
    try:
        up = Upstream(upstream_argv)
    except (UpstreamError, OSError) as exc:
        print(f"oathline-guard: cannot start the upstream server: {exc}", file=sys.stderr)
        return 2
    try:
        guard = Guard(a.server, up, reads, os.path.join(a.home, a.server))
        return guard.serve()
    except UpstreamError as exc:
        print(f"oathline-guard: {exc}", file=sys.stderr)
        return 2
    finally:
        up.close()
