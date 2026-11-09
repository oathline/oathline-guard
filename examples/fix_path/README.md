# The fix path, Stage 1: SIYA pushes a fix after approval

A coding agent (Claude Code) fixes a website, but the only tools it has that can change anything are two MCP servers that
oathline-guard holds. Every change waits for the person's typed code, runs once with exactly the arguments shown, and is
recorded in the guard's hash-chained log. This is Stage 1 of the authority ladder in SITE_WATCH_PLAN section 2.5:
**the edit, the commit, the push of a work branch, and the pull request**. There is no merge, no deploy, no force, no delete,
and the base branch is never pushed: Stages 2 (merge and preview) and 3 (production) are not granted here.

| Server | Reads (pass) | Held (each needs its own yes) |
|---|---|---|
| `fix_fs.py --root <site>` | `read_file`, `list_directory` | `edit_file(path, old_text, new_text)`: one exact replacement, `old_text` must occur once |
| `fix_git.py --repo <site> --base main --remote origin` | `git_status`, `git_diff` | `git_commit(branch, message)`, `git_push(branch, commit)`, `open_pr(branch, title, body)` |

What the person sees and approves is exact:
- `edit_file` shows `old_text` and `new_text` verbatim (a multi-line text as a block behind `| `); the file then holds exactly
  the shown new text.
- `git_push` shows the branch and the commit; the server pushes only if the branch's head IS that commit, so what is pushed is
  what was committed after the approved edits; git itself refuses a non-fast-forward (no force exists).
- `open_pr` shows the title and body; the token that opens it is the server's (its environment), never an argument, never shown,
  never in the guard's files.
- A yes runs that one call once. The same call again is a new request; a call with any other argument waits for its own yes.

## Running a fix session

1. Put the real paths and the person's name into `mcp.json`; put a **fine-grained token for that one repository** (contents and
   pull requests: write; nothing else) into the `git` server's `env`, never into a prompt.
2. Start the approve windows, one per server, in their own terminals: `oathline-guard approve --server fs` and
   `oathline-guard approve --server git`.
3. Start Claude Code with the recipe, its own write tools denied and only these servers:
   `claude --settings claude_settings.json --mcp-config mcp.json --strict-mcp-config`
   Check at the start that `/permissions` lists Edit, Write, MultiEdit, NotebookEdit and Bash as denied.
4. Ask for the fix. Each edit, the commit, the push and the PR wait for the code in the matching window.

## Tested

`tests/test_w5_fix_path.py` runs the whole path against a fixture site repository, a local bare repository as its remote and a
fake pull-request API on 127.0.0.1: nothing touches a real remote.

## Limits

- An agent with a raw shell goes around any MCP guard: that is why the recipe denies Bash and the native write tools. Check it.
- The guard does not wait for the yes (the agent retries the same call after it), and an upstream call has no timeout yet.
- One person per server; the terminal is the only approval channel.
