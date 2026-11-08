"""Misbehaving and unusual upstream MCP servers for the Guard's tests (FABLE 16:58 review of G0-G2).

    python -m tests.fake_upstreams MODE
MODE:
  asks     sends the Guard a request (roots/list) before it answers tools/list; waits for the Guard's answer, records it
  pages    tools/list in two pages (nextCursor "p2"): page 1 = read_a, page 2 = read_b + write_b
  grows    after the first tools/call it adds `new_tool` (readOnlyHint true) and sends notifications/tools/list_changed
  dies     answers initialize and tools/list, then exits on the first tools/call
  early    like grows, but sends list_changed BEFORE its tools/call answer (the client must see it first: "as it arrives")
  mute     on the first tools/call closes its stdout and stays alive (FABLE 17:30, R3 residual a)
  chatty   sends a log notification right after its own initialize answer, before the client has initialized the Guard
  badbyte  right after its initialize answer writes one line that is not UTF-8 (a stray log byte), then serves normally
  idle     exits on its own one second after its first tools/list, with no call in flight (FABLE 17:30, R3 residual b)
Every tool returns "<name> ran" and appends the call to the file named by $FAKE_LOG (one JSON line per call).
"""
import json
import os
import sys
import threading
import time

TOOLS_A = [{"name": "read_a", "description": "a read", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}}]
TOOLS_B = [{"name": "read_b", "description": "a read on page 2", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}},
           {"name": "write_b", "description": "a write on page 2", "inputSchema": {"type": "object"}}]
NEW = {"name": "new_tool", "description": "Totally harmless.", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}}


def out(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def log(entry):
    path = os.environ.get("FAKE_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")


def main(mode):
    tools = list(TOOLS_A + TOOLS_B)
    asked = False
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        if "id" not in msg:
            continue
        mid, method, params = msg["id"], msg.get("method"), msg.get("params") or {}
        if method is None:                                   # an answer to our own request (asks mode)
            log({"answer_to_our_request": msg})
            continue
        if method == "initialize":
            out({"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2025-06-18",
                                                         "capabilities": {"tools": {"listChanged": True}},
                                                         "serverInfo": {"name": f"fake-{mode}", "version": "0"}}})
            if mode == "badbyte":
                sys.stdout.flush()
                sys.stdout.buffer.write(b"ÿþ stray bytes from a log line
")
                sys.stdout.buffer.flush()
            if mode == "chatty":
                out({"jsonrpc": "2.0", "method": "notifications/message", "params": {"level": "info", "data": "hello early"}})
        elif method == "tools/list":
            if mode == "asks" and not asked:
                asked = True
                out({"jsonrpc": "2.0", "id": "up-1", "method": "roots/list"})       # the upstream asks first
                answer = json.loads(sys.stdin.readline())
                log({"answer_to_our_request": answer})
            if mode == "pages":
                if params.get("cursor") == "p2":
                    out({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS_B}})
                else:
                    out({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS_A, "nextCursor": "p2"}})
            else:
                out({"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}})
            if mode == "idle":
                threading.Timer(1.0, lambda: os._exit(4)).start()
        elif method == "tools/call":
            if mode == "dies":
                sys.exit(3)
            if mode == "mute":
                sys.stdout.flush()
                os.close(1)
                time.sleep(60)
                return
            name = params.get("name")
            if mode == "early" and NEW not in tools:
                tools.append(NEW)
                out({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
            log({"call": name})
            out({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": f"{name} ran"}], "isError": False}})
            if mode == "grows" and NEW not in tools:
                tools.append(NEW)
                out({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
        else:
            out({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}})


if __name__ == "__main__":
    main(sys.argv[1])
