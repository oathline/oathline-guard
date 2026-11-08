"""A scripted MCP client over stdio: it stands in for the model's client (Claude Code / Desktop) in every test. It can ask; it has
no way to answer an approval (the approval is the human's, in another process)."""
import json
import os
import queue
import subprocess
import sys
import threading

from tests import _core


def env(extra_path=()):
    return dict(os.environ, PYTHONPATH=os.pathsep.join([_core.ROOT, *extra_path]), PYTHONIOENCODING="utf-8")


class Client:
    def __init__(self, argv, *, cwd=None, extra_env=None):
        e = env()
        e.update(extra_env or {})
        self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                  encoding="utf-8", cwd=cwd or _core.ROOT, env=e)
        self.n = 0
        self.notifications = []
        self.lines: queue.Queue = queue.Queue()
        self.stderr_lines: list[str] = []
        threading.Thread(target=self._pump, args=(self.p.stdout, self.lines.put, True), daemon=True).start()
        threading.Thread(target=self._pump, args=(self.p.stderr, self.stderr_lines.append), daemon=True).start()   # FABLE 16:58: drained

    @staticmethod
    def _pump(stream, sink, end_marker=False):
        try:
            for line in stream:
                sink(line)
        except (ValueError, OSError):
            pass
        if end_marker:                                       # the stdout pump marks the end of output (FABLE 17:30 nit: plainer)
            sink(None)

    def send(self, obj):
        self.p.stdin.write((obj if isinstance(obj, str) else json.dumps(obj)) + "\n")
        self.p.stdin.flush()

    def recv(self, timeout: float = 20.0):
        """The next response; notifications are kept aside. A server that says nothing for `timeout` seconds fails the test, never
        hangs it (FABLE 16:58, R1: a Guard that deadlocks must show up as a failure)."""
        while True:
            try:
                line = self.lines.get(timeout=timeout)
            except queue.Empty:
                raise TimeoutError(f"no answer in {timeout:g} s; stderr: " + "".join(self.stderr_lines)[-2000:]) from None
            if line is None:
                raise EOFError("the server closed its stdout; stderr: " + "".join(self.stderr_lines)[-2000:])
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

    def wait_notification(self, method: str, timeout: float = 5.0) -> bool:
        """True when a notification `method` arrives within `timeout`, WITHOUT sending anything (a server that hands notifications on
        only when asked something is not 'as it arrives')."""
        import time as _t
        if any(n.get("method") == method for n in self.notifications):
            return True
        end = _t.monotonic() + timeout
        while _t.monotonic() < end:
            try:
                line = self.lines.get(timeout=max(0.05, end - _t.monotonic()))
            except queue.Empty:
                return False
            if line is None:
                return False
            msg = json.loads(line)
            if isinstance(msg, dict) and "id" not in msg and "method" in msg:
                self.notifications.append(msg)
                if msg.get("method") == method:
                    return True
        return False

    def rest(self, timeout: float = 5.0) -> list[str]:
        """Every line the server still writes until it closes its stdout (after stdin is closed)."""
        out = []
        while True:
            try:
                line = self.lines.get(timeout=timeout)
            except queue.Empty:
                return out
            if line is None:
                return out
            out.append(line)

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
