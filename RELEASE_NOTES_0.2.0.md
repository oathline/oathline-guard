# oathline-guard 0.2.0

**What changed:** the Guard runs on Oathline Core 0.3 and gains one read-only command:

    oathline-guard log --server NAME [--since N] [--verify]

It prints what the Guard recorded for that server after event N (Core numbers every event, inside its hash), and with --verify,
whether that part of the record still holds.

**Long values are checked by Core.** A long or multi-line argument (a file to write, a long query) is still shown whole in the
approve window, every line behind "| ". Oathline Core 0.3 now checks that block itself before it records SHOWN, instead of the
Guard doing it. If you read error codes: a block that does not match the value is now `carried_hash_mismatch` (0.1.0 said
`shown_body_differs`), and a value with Windows line ends shows and runs with exactly those bytes.

**An upstream that has ended is failed closed.** The call in flight answers an error, the Guard ends the upstream's whole process
tree and exits 1. An upstream that dies is noticed however it was started; one that closes its output while it keeps running is
noticed when started directly or as a venv's python.exe, and behind another wrapper (npx, a .cmd, a console-script .exe) only
when it exits: there is no timeout yet.

The rest is as in 0.1.0: reads pass, every other tool call waits for a coded yes in the approve window, and the yes runs exactly
what was shown, once.

The SHA-256 of each file attached to this release is on the release page, not in the package.
