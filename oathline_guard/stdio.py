"""Newline-delimited JSON-RPC 2.0 over stdio (the MCP stdio transport): framing and message helpers, shared by the Guard (server to the
client, client to the upstream server) and the demo server."""
from __future__ import annotations

import json

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")


def result(mid, res) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": res}


def error(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def write(stream, obj) -> None:
    """One message per line; stdout carries JSON-RPC only."""
    stream.write(json.dumps(obj, ensure_ascii=False) + "\n")
    stream.flush()


def read(stream):
    """The next message from a stream, or None at end of input. A line that is not JSON is returned as the string '<parse error>'."""
    while True:
        line = stream.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except ValueError:
            return "<parse error>"


def agreed_version(asked) -> str:
    return asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]


def text_result(text: str, *, is_error: bool = False, structured=None) -> dict:
    out = {"content": [{"type": "text", "text": text}], "isError": bool(is_error)}
    if structured is not None:
        out["structuredContent"] = structured
    return out
