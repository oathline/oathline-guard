# Changelog

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
