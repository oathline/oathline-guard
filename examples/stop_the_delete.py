"""Stop the delete: the PocketOS scene through oathline-guard, scripted end to end (no model, no network, no terminal needed).

An agent told to "clean up the old database" asks fake-db-mcp to delete prod's backups and to drop prod. oathline-guard holds both,
the person sees exactly what would run and says no; they say yes, with the code, to dropping staging; it runs once. Run it:

    python examples/stop_the_delete.py

(In real use the person types into `python -m oathline_guard approve --server db` in a second terminal; here the answers are scripted,
which is the only reason the window's terminal check is bypassed below.)
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from oathline_guard import approve  # noqa: E402
from oathline_guard.record import Record  # noqa: E402

work = tempfile.mkdtemp(prefix="stop-the-delete-")
home, state = os.path.join(work, "home"), os.path.join(work, "db.json")
with open(os.path.join(work, "reads.json"), "w", encoding="utf-8") as fh:
    json.dump({"server": "db", "reads": ["list_databases", "list_tables"]}, fh)
guard = subprocess.Popen([sys.executable, "-m", "oathline_guard", "run", "--server", "db", "--reads", os.path.join(work, "reads.json"),
                          "--home", home, "--human", "saroj", "--", sys.executable, "-m", "oathline_guard.demo.fake_db", "--state", state],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8", cwd=ROOT)
n = 0


def agent(name, args=None):
    global n
    n += 1
    guard.stdin.write(json.dumps({"jsonrpc": "2.0", "id": n, "method": "tools/call", "params": {"name": name, "arguments": args or {}}}) + "\n")
    guard.stdin.flush()
    return json.loads(guard.stdout.readline())["result"]["content"][0]["text"]


def person(*answers):
    rec, out, queue = Record(os.path.join(home, "db"), "db"), io.StringIO(), list(answers)
    approve.window(rec, ask=lambda p, call: rec.code(call) if queue.pop(0) == "CODE" else "n", out=out, isatty=lambda: True, once=True)
    rec.close()
    return out.getvalue()


guard.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}) + "\n")
guard.stdin.flush()
guard.stdout.readline()
print("agent: list_databases ->", agent("list_databases"))
for tool, name, answer in (("delete_backups", "prod", "n"), ("drop_database", "prod", "n"), ("drop_database", "staging", "CODE")):
    print(f"\nagent: {tool}({name!r}) ->", agent(tool, {"name": name})[:60], "...")
    print("person's window:" + person(answer).replace("\n", "\n  "))
    print(f"agent retries {tool}({name!r}) ->", agent(tool, {"name": name}))
with open(state, encoding="utf-8") as fh:
    world = json.load(fh)
print("\nprod and its backups:", "intact" if world.get("prod", {}).get("backups") == ["prod-2026-11-07", "prod-2026-11-08"] else "GONE")
print("staging:", "dropped once" if "staging" not in world else "still there")
rec = Record(os.path.join(home, "db"), "db")
eng = rec.engine()
print("events:", " ".join(e["event_type"] for e in eng.audit.events()))
print("chain ok:", eng.audit.verify()["ok"])
rec.close()
guard.stdin.close()
guard.wait(timeout=10)
shutil.rmtree(work, ignore_errors=True)
