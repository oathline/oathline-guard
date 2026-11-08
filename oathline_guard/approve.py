"""`oathline-guard approve`: the person's window (OATHLINE_GUARD_PLAN section 5, as amended after FABLE 15:47; G4, FABLE 20:01).

    python -m oathline_guard approve --server NAME [--home DIR] [--once]

For each call waiting for a yes it prints the Guard's own text (the tool, every argument in the Guard's words, long values whole
behind "| ", the code last), re-hashes the blocks and records SHOWN, then takes what the person types: the right code is the yes
ROW, `n` is a RECORDED no, a wrong code decides nothing and asks again. HEARD is recorded on the first answer typed, whatever it is
(a wrong code or `n` included): the person demonstrably had the text in front of them; nothing else is written on a wrong code.
It never confirms and never runs anything: the Guard process, which holds the server's pipe, runs the call on the agent's next
identical call. It reads only from a terminal (an agent's shell tool cannot type the code; a pseudo-terminal does satisfy the
check, which is this rule's known limit) and only for the person the Guard was started with.

Within one window: an expired call is never printed (its code included), "expired" is said once; a call shown and left unanswered is
not shown again until the window is restarted; a text the console cannot encode is not printed and not SHOWN ("cannot display").
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from .record import Record, server_name_ok

PROMPT = "Type the code to run it, or n to refuse: "
TRIES = 3


class NotATerminal(Exception):
    pass


def _stdin_is_terminal() -> bool:
    try:
        return bool(sys.stdin.isatty())
    except Exception:  # noqa: BLE001
        return False


def _can_display(text: str, out) -> bool:
    """The console can show these exact characters (FABLE 20:01: otherwise it crashes, or shows '??' while SHOWN hashes the text)."""
    try:
        encoding = out.encoding or "utf-8"
    except AttributeError:                                # a plain StringIO: str in, str out
        encoding = "utf-8"
    try:
        text.encode(encoding, "strict")
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def window(rec: Record, *, ask, out, isatty=_stdin_is_terminal, once: bool = False, poll: float = 1.0, max_rounds=None) -> int:
    """Answer the waiting calls; with once=True those waiting now, then return; max_rounds bounds the loop (tests). -> how many
    calls were answered. `ask(prompt, call) -> str` reads one line from the person; `out` is where the text is printed."""
    if not isatty():
        raise NotATerminal("the code must be typed by a person at a terminal; stdin is not one")
    human = rec.human
    answered, rounds = 0, 0
    seen: set = set()                                     # shown in this window and left unanswered: not shown again
    said_empty = False
    while True:
        rounds += 1
        for call in rec.expire_due():
            print(f"({call} expired before an answer; nothing decided, nothing will run)", file=out)
        waiting = [row for row in rec.pending() if row["call"] not in seen]
        if not waiting and once and answered == 0 and not said_empty:
            print("Nothing is waiting for a yes.", file=out)
            said_empty = True
        for row in waiting:
            call = row["call"]
            seen.add(call)
            text = rec.text(call)
            if not _can_display(text, out):
                print(f"({call}: this console cannot display the text; nothing shown or decided. Use a UTF-8 terminal.)", file=out)
                continue
            print("", file=out)
            print(text, file=out)
            shown = rec.show(call, text)
            if not shown.get("ok"):
                print(f"(not shown: {shown.get('error')}; nothing decided for {call})", file=out)
                continue
            heard = False
            for _ in range(TRIES):
                answer = str(ask(PROMPT, call) or "").strip()
                if not answer:
                    continue
                if not heard:
                    h = rec.hear(call)
                    if not h.get("ok"):
                        print(f"(not heard: {h.get('error')}; nothing decided for {call})", file=out)
                        break
                    heard = True
                if answer.lower() in ("n", "no"):
                    rec.no(call, human)
                    print(f"Refused and recorded ({call}). Nothing will run.", file=out)
                    answered += 1
                    break
                if rec.yes(call, answer, human):
                    print(f"Yes recorded ({call}). It runs once, on the agent's next identical call.", file=out)
                    answered += 1
                    break
                print("Wrong code: nothing decided. Read the text again and type its code.", file=out)
            else:
                print(f"No answer for {call}; it stays waiting (restart the window to see it again).", file=out)
        if once or (max_rounds is not None and rounds >= max_rounds):
            return answered
        time.sleep(poll)


def main(argv: list[str]) -> int:
    if not _stdin_is_terminal():                          # FABLE 20:01 nit: the terminal rule first, before anything is opened
        print("oathline-guard approve: refused: the code must be typed by a person at a terminal; stdin is not one", file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser(prog="oathline-guard approve")
    ap.add_argument("--server", required=True)
    ap.add_argument("--home", default=os.path.join(os.path.expanduser("~"), ".oathline-guard"))
    ap.add_argument("--once", action="store_true", help="answer what is waiting now, then exit")
    a = ap.parse_args(argv)
    if not server_name_ok(a.server):
        print(f"oathline-guard approve: --server {a.server!r} must be one plain name (letters, digits, '_', '.', '-')", file=sys.stderr)
        return 2
    folder = os.path.join(a.home, a.server)
    if not os.path.isfile(os.path.join(folder, "guard.db")):
        print(f"oathline-guard approve: no guard record for server {a.server!r} in {a.home} (start the guard with --human first)",
              file=sys.stderr)
        return 2
    # the console's encoding is left as it is (FABLE 20:29): forcing UTF-8 would make _can_display always pass and send UTF-8 bytes
    # to a console that shows something else; a console that cannot encode the text is told so and nothing is SHOWN
    rec = Record(folder, a.server)
    try:
        if not rec.human:
            print("oathline-guard approve: the guard was started without --human: nobody can answer", file=sys.stderr)
            return 2
        try:
            # the same terminal check main() made, looked up now (a default argument is bound when window() is defined)
            window(rec, ask=lambda prompt, call: input(prompt), out=sys.stdout, once=a.once, isatty=lambda: _stdin_is_terminal())
        except NotATerminal as exc:
            print(f"oathline-guard approve: refused: {exc}", file=sys.stderr)
            return 2
        except (KeyboardInterrupt, EOFError):
            print("", file=sys.stdout)
            return 130
        return 0
    finally:
        rec.close()
