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

**2. Write the read list**, the tools that pass without a yes. Save it as `reads.json` in a folder of your choice:

```json
{"server": "db", "reads": ["list_databases", "list_tables"]}
```

**3. Add the guarded demo server to Claude Desktop.** Open `claude_desktop_config.json` (Settings > Developer > Edit Config;
on macOS it is in `~/Library/Application Support/Claude/`, on Windows in `%APPDATA%\Claude\`), put in your own folder and name,
then restart Claude Desktop:

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
no protection of its own. If `oathline-guard` is not on your PATH, use the full path that `pip` printed.

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
  line of its own; long values are shown whole and bound by hash.
- The yes runs the stored arguments exactly once. A wrong code decides nothing; a no is recorded, and a later yes is too late.
- The approve window reads only from a terminal: an agent's shell tool cannot pipe the code in.

Limits, said plainly:

- **A pseudo-terminal passes the terminal check.** It stops a pipe, not a determined local process with a pty.
- **An agent with a raw shell or a raw token goes around any MCP guard.** The guard governs the calls that pass through it;
  switch off the client's own write tools for the session if the guard must be the only way to act.
- **No timeout on an upstream call yet**, and the agent retries after the yes (no waiting notification yet). On Windows, when
  the upstream is started through a virtual environment's `python.exe` (a launcher that holds the pipes), an upstream that
  closes its output but keeps running is noticed only when it exits.
- **stdio servers only**; one person per guarded server; the terminal is the only approval channel.
- **Secret arguments are not masked yet**: a secret in an argument is shown in the window.
- **Heard is not understood:** the record proves the words were shown and answered, not that they were read.

## The record

Each guarded server keeps its own folder (default `~/.oathline-guard/<server>/`) with Oathline Core's audit chain and token
store. The chain for one call reads `REQUEST AUTHORIZED PROPOSED_BY_AGENT SHOWN HEARD CONFIRMED_BY_HUMAN EXECUTING EXECUTED`, or
ends at `REFUSED_BY_HUMAN`; `verify()` on the audit log checks every link.

## Licence

MIT. Copyright (c) 2026 Nexxt Nest Group Pty Ltd. Built on [Oathline Core](https://pypi.org/project/oathline/).

<!-- mcp-name: io.github.oathline/oathline-guard -->
