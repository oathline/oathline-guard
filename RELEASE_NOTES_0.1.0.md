oathline-guard 0.1.0 is the first release: an MCP guard where an AI agent's yes means exactly what the person saw.

It wraps any stdio MCP server. Reads on your list pass. Every other tool call waits until a person, in a second terminal
(`oathline-guard approve`), sees the exact call in the guard's own words and types its code; then it runs once, with exactly
those arguments, and Oathline Core 0.2.0's hash-chained log records what was shown, heard, confirmed and run. The agent never
receives the code.

Install: `pip install oathline-guard` (Python 3.10+, depends only on `oathline>=0.2.0,<0.3`). The README's quickstart runs the
guard in front of a demo database server in about five minutes.

Limits in this release, also on the README's first page: a pseudo-terminal passes the terminal check; an agent with a raw shell
goes around any MCP guard; no upstream timeout and no waiting notification yet; stdio only; secret arguments are shown, not
masked.

Checksums of the wheel and the sdist are on this release page (SHA256SUMS). These notes are the release page's and are not
shipped in the package.
