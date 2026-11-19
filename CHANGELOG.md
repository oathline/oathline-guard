# Changelog

## 0.2.0

On Oathline Core 0.3 (`oathline>=0.3.0,<0.4`).

- `oathline-guard log --server NAME [--home DIR] [--since N] [--verify]`: the server's Core events after event N as JSON lines,
  by Core 0.3.0's `events(since_seq)` (every event carries `seq` in its hashed body); `--verify` adds Core's report for the same
  range (`verify(from_seq)`) and exits 1 when it does not hold. Read-only: never creates or writes the record; exit 2 when the server
  has none.
- Long values are Core 0.3.0 block items. A long or multi-line argument is stored in Core as `{"sha256", "chars"}`, an item
  `carried: "block"` labelled with its key (the Guard declares each tool's keys in `block_keys`), and still shown whole in the
  approve window under "<key>:", every line "| ", closed by "--- end of <key> ---". Core's `show()` now finds that block, takes the
  marks off and checks its SHA-256 and length; the Guard's own re-hash is gone. A window whose block differs from the value is refused
  with Core's `carried_hash_mismatch` (0.1.0 said `shown_body_differs`); a window with two blocks under one key is `item_not_in_text`.
  A value with Windows line ends ("\r\n") shows and runs with exactly those bytes.
- An upstream that has ended is failed closed: the call in flight answers an error, the guard kills the upstream's WHOLE process
  tree (Windows `taskkill /T`; elsewhere its own process group) and exits 1. An upstream that dies is noticed however it was
  started; one that closes its output while it keeps running is noticed when started directly or as a venv's python.exe, and behind
  another wrapper (npx, a .cmd, a console-script .exe) only when it exits: there is no timeout yet. A virtual environment's `python.exe` on Windows is started as its real interpreter with
  `__PYVENV_LAUNCHER__`, as CPython's own multiprocessing does: the launcher used to hold the pipe, so a closed output was never seen
  and a kill reached the launcher only.
- Unchanged: reads pass, every other tool call waits for a coded yes in the approve window, and the yes runs exactly what was shown,
  once.

## 0.1.0

The first release. An MCP guard on Oathline Core 0.2.0 (the hearing rule).

- `oathline-guard run --server NAME --reads FILE --human NAME -- <server command>`: a stdio proxy between an MCP client and a
  real server. Tools on the read list pass; every other tool call is held as an Oathline proposal and answered "Not run ...
  waiting"; the server is not called. Tool annotations from the server (`readOnlyHint`) never make a tool a read; no read list
  means nothing passes.
- `oathline-guard approve --server NAME [--once]`: the person's window, terminal only. It shows the held call in the guard's own
  words (the tool, every argument; a value cannot write a line of its own; long values whole, bound by hash), records SHOWN and
  HEARD, and takes the four-character code (a yes) or `n` (a recorded no). A wrong code decides nothing.
- After the yes, the agent's next identical call runs the stored arguments exactly once; a call with other arguments is a new
  proposal. Expired calls are never shown.
- `--shown-text` keeps the shown words in the chain (default: their hash only).
- `oathline_guard.demo.fake_db`: the demo database server of the quickstart.
- `oathline_guard.registry:for_server`: the read-only hook the oathline-agent reader uses to name the guard's capabilities.

Not in 0.1.0: waiting with progress notifications (the agent retries after the yes), a timeout on upstream calls, `init` and
`demo` commands, masking secret arguments, an approval channel other than the terminal, streamable HTTP servers.
