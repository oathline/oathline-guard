# oathline-guard

**An AI agent's yes means exactly what the person saw.**

oathline-guard sits between your MCP client (Claude Desktop, Claude Code, Cursor) and a real stdio MCP server. Reads you list
pass straight through. Every other tool call waits: a person, in a second terminal, sees the exact call in the guard's own words
and types its four-character code. Then it runs once, with exactly those arguments, and [Oathline](https://github.com/oathline/oathline)'s
hash-chained log records what was shown, heard, confirmed and run.

In April 2026 a coding agent deleted a production database and its backups in nine seconds, with no approval step. This is the
same request, through the guard:

```text
db / drop_database
name: prod
code: 44NF
Type the code to run it, or n to refuse: n
Refused and recorded (c-508e50ec). Nothing will run.
```

The agent only ever gets "Not run ... waiting for a person's yes"; the code is never sent to it, so it cannot approve itself.

## Quickstart (about 5 minutes, with the demo database)

**1. Install** (Python 3.10 or later):

```
pip install oathline-guard
```

**2. Prepare the demo:**

```
oathline-guard demo
```

It writes the read list (the tools that pass without a yes) to `~/oathline-guard-demo/reads.json`:

```json
{"server": "db", "reads": ["list_databases", "list_tables"]}
```

and prints the block for Claude Desktop with your machine's real paths (it runs everything through the Python you installed
with, so `PATH` and `python` vs `python3` do not matter). It approves nothing and runs nothing.

**3. Add the block to Claude Desktop.** Open `claude_desktop_config.json` (Settings > Developer > Edit Config; on macOS it is
in `~/Library/Application Support/Claude/`, on Windows in `%APPDATA%\Claude\`), paste the printed block, then restart Claude
Desktop. By hand, the block has this shape:

```json
{
  "mcpServers": {
    "db": {
      "command": "oathline-guard",
      "args": ["run", "--server", "db", "--reads", "/path/to/reads.json", "--human", "you",
               "--", "python", "-m", "oathline_guard.demo.fake_db", "--state", "/path/to/db.json"]
    }
  }
}
```

`oathline_guard.demo.fake_db` is a tiny database server with two reads and two writes (`drop_database`, `delete_backups`) and
no protection of its own. Claude Desktop starts it with a short PATH: written by hand, if `oathline-guard` is not found, use
the full path that `pip` printed, and if `python` is not found (on macOS often only `python3` exists), write `python3` or the
interpreter's full path. The block `oathline-guard demo` prints avoids both.

**4. Open the approve window** in a second terminal and leave it open:

```
oathline-guard approve --server db
```

**5. Ask Claude:** "clean up the old database". The reads run. The drop waits, and the approve window shows it as above: type
`n` to refuse, or the code to let it run once. After a yes, the agent's next identical call runs it; a call with different
arguments is a new request that waits again.

To guard a real server, put its own command after `--` and list its read-only tools in `reads.json`. Tools not on the list
always wait, whatever the server's own annotations (`readOnlyHint`) say.

## What it guarantees, and what it does not

- Reads on your list pass untouched; everything else is held, and the real server is not called until the yes.
- The words in the window are the guard's: the tool and every argument, never the server's description. A value cannot add a
  line of its own; long values are shown whole and bound by hash, up to 16,000 characters of window text and Oathline Core's
  8 KB cap on a call's items. A call beyond either is refused before anything is shown (`text_too_large`, `items_too_large`):
  split it.
- The yes runs the stored arguments exactly once. A wrong code decides nothing; a no is recorded, and a later yes is too late.
  A held call waits 15 minutes for its yes (the agent is told "expires HH:MM"); after that it is a new request. After a no, the
  same call asked of the same guard is answered "the person said no"; asked of a NEW guard process, it is a new request and is
  shown again.
- The approve window reads only from a terminal: an agent's shell tool cannot pipe the code in.

Limits, said plainly:

- **A pseudo-terminal passes the terminal check.** It stops a pipe, not a determined local process with a pty.
- **An agent with a raw shell or a raw token goes around any MCP guard.** The guard governs the calls that pass through it;
  switch off the client's own write tools for the session if the guard must be the only way to act.
- **No timeout on an upstream call yet**, and the agent retries after the yes (no waiting notification yet). When the guard
  notices that an upstream has ended, the call in flight answers an error, the guard kills the upstream and its whole process tree
  and exits 1, so the client can restart it. What it notices: an upstream that dies is noticed however it was started; one that
  closes its output while it keeps running is noticed when started directly or as a venv's python.exe, and behind another wrapper
  (npx, a .cmd, a console-script .exe) only when it exits: there is no timeout yet. An upstream that stays connected but never
  answers waits.
- **The record proves edits, not a rewrite.** A hash chain detects edits; it does not stop someone who can write
  `~/.oathline-guard/<server>/` from rewriting the record and recomputing every hash. To catch that, keep the head outside the
  machine (see **The record** below).
- **stdio servers only**; one person per guarded server; the terminal is the only approval channel.
- **Secret arguments are not masked yet**: a secret in an argument is shown in the window.
- **Heard is not understood:** the record proves the words were shown and answered, not that they were read.

## The record

Each guarded server keeps its own folder (default `~/.oathline-guard/<server>/`) with Oathline Core's audit chain and token
store. The chain for one call reads `REQUEST AUTHORIZED PROPOSED_BY_AGENT SHOWN HEARD CONFIRMED_BY_HUMAN EXECUTING EXECUTED`, or
ends at `REFUSED_BY_HUMAN`; `verify()` on the audit log checks every link.

A hash chain detects edits; it does not stop someone who can write `~/.oathline-guard/<server>/` from rewriting the record and
recomputing every hash. To catch that, keep the head outside the machine, with Oathline Core's own commands:

```
python -m oathline anchor --store ~/.oathline-guard/db/audit.db
python -m oathline verify --store ~/.oathline-guard/db/audit.db --expected-head <head> --anchor-seq <seq>
```

The first prints the `head` and `seq` to keep somewhere the record's writer cannot reach; the second, later, exits 1 if the record
was cut short or rewritten up to that event. An anchor proves the past up to its `seq`, nothing after it.

To read it, `oathline-guard log --server db` prints the server's events as JSON lines; `--since N` starts after event N, and
`--verify` also checks that part of the chain (exit 1 when it does not hold). It only reads: it never creates or writes a record.

```
oathline-guard log --server db --verify
```

## Who built it

Built by Saroj Sanjel with AI coding agents: every change test-first, independently reviewed, approved by a human before release.

## Licence

MIT. Copyright (c) 2026 Nexxt Nest Group Pty Ltd. Built on [Oathline Core](https://pypi.org/project/oathline/).

<!-- mcp-name: io.github.oathline/oathline-guard -->
