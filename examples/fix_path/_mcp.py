"""The tiny stdio MCP loop the two fix-path servers share (the same shape as oathline_guard.demo.fake_db)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from oathline_guard import stdio  # noqa: E402


def serve(name: str, tools: list, call) -> int:
    """`call(tool_name, arguments) -> (text, is_error)`."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    names = {t["name"] for t in tools}
    while True:
        msg = stdio.read(sys.stdin)
        if msg is None:
            return 0
        if msg == "<parse error>":
            stdio.write(sys.stdout, stdio.error(None, -32700, "parse error"))
            continue
        if not isinstance(msg, dict) or "id" not in msg:
            continue
        mid, method, params = msg["id"], msg.get("method"), msg.get("params") or {}
        if method == "initialize":
            stdio.write(sys.stdout, stdio.result(mid, {"protocolVersion": stdio.agreed_version(params.get("protocolVersion")),
                                                       "capabilities": {"tools": {"listChanged": False}},
                                                       "serverInfo": {"name": name, "version": "0.1"}}))
        elif method == "ping":
            stdio.write(sys.stdout, stdio.result(mid, {}))
        elif method == "tools/list":
            stdio.write(sys.stdout, stdio.result(mid, {"tools": tools}))
        elif method == "tools/call":
            tool = params.get("name")
            if tool not in names:
                stdio.write(sys.stdout, stdio.error(mid, -32602, f"unknown tool: {tool}"))
                continue
            try:
                text, is_error = call(tool, params.get("arguments") or {})
            except Exception as e:  # noqa: BLE001
                text, is_error = f"{type(e).__name__}: {e}", True
            stdio.write(sys.stdout, stdio.result(mid, stdio.text_result(text, is_error=is_error)))
        else:
            stdio.write(sys.stdout, stdio.error(mid, -32601, f"method not found: {method}"))


def schema(props: dict, required=()) -> dict:
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}
