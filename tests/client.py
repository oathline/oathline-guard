"""A scripted MCP client over stdio: it stands in for the model's client (Claude Code / Desktop) in every test. It can ask; it has
no way to answer an approval (the approval is the human's, in another process)."""
import json
import os
import subprocess
import sys

from tests import _core


def env(extra_path=()):
    return dict(os.environ, PYTHONPATH=os.pathsep.join([_core.CORE, _core.ROOT, *extra_path]), PYTHONIOENCODING="utf-8")


class Client:
    def __init__(self, argv, *, cwd=None, extra_env=None):
        e = env()
        e.update(extra_env or {})
        self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                  encoding="utf-8", cwd=cwd or _core.ROOT, env=e)
        self.n = 0
        self.notifications = []

    def send(self, obj):
        self.p.stdin.write((obj if isinstance(obj, str) else json.dumps(obj)) + "\n")
        self.p.stdin.flush()

    def recv(self):
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise EOFError("the server closed its stdout: " + self.p.stderr.read()[-2000:])
            msg = json.loads(line)
            if isinstance(msg, dict) and "id" not in msg and "method" in msg:
                self.notifications.append(msg)              # progress, list_changed ...: kept, not a response
                continue
            return msg

    def call(self, method, params=None):
        self.n += 1
        msg = {"jsonrpc": "2.0", "id": self.n, "method": method}
        if params is not None:
            msg["params"] = params
        self.send(msg)
        return self.recv()

    def notify(self, method, params=None):
        self.send({"jsonrpc": "2.0", "method": method, **({"params": params} if params is not None else {})})

    def start(self):
        r = self.call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                     "clientInfo": {"name": "scripted-agent", "version": "0"}})
        self.notify("notifications/initialized")
        return r

    def tools(self):
        return self.call("tools/list")["result"]["tools"]

    def tool(self, name, args=None, meta=None):
        params = {"name": name, "arguments": args or {}}
        if meta:
            params["_meta"] = meta
        return self.call("tools/call", params)

    def close(self):
        try:
            self.p.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.p.kill()
            self.p.wait(timeout=5)
        for s in (self.p.stdout, self.p.stderr):
            try:
                s.close()
            except Exception:  # noqa: BLE001
                pass


def fake_db_argv(state_path):
    return [sys.executable, "-m", "oathline_guard.demo.fake_db", "--state", state_path]
