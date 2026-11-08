"""`oathline-guard approve`: the person's window (OATHLINE_GUARD_PLAN section 5, as amended after FABLE 15:47; G4).

    python -m oathline_guard approve --server NAME [--home DIR] [--once]

For each call waiting for a yes it prints the Guard's own text (the tool, every argument in the Guard's words, long values whole
behind "| ", the code last), re-hashes the blocks and records SHOWN, then takes what the person types and records HEARD: the right
code is the yes ROW, `n` is a RECORDED no, a wrong code decides nothing and asks again. It never confirms and never runs anything:
the Guard process, which holds the server's pipe, runs the call on the agent's next identical call. It reads only from a terminal
(an agent's shell tool cannot type the code) and only for the person the Guard was started with.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from .record import Record

PROMPT = "Type the code to run it, or n to refuse: "
TRIES = 3


class NotATerminal(Exception):
    pass


def _stdin_is_terminal() -> bool:
    try:
        return bool(sys.stdin.isatty())
    except Exception:  # noqa: BLE001
        return False


def window(rec: Record, *, ask, out, isatty=_stdin_is_terminal, once: bool = False, poll: float = 1.0) -> int:
    """Answer every waiting call; with once=True, those waiting now, then return. -> how many calls were answered.
    `ask(prompt, call) -> str` reads one line from the person; `out` is where the text is printed."""
    if not isatty():
        raise NotATerminal("the code must be typed by a person at a terminal; stdin is not one")
    human = rec.human
    answered = 0
    while True:
        waiting = rec.pending()
        if not waiting and once:
            if answered == 0:
                print("Nothing is waiting for a yes.", file=out)
            return answered
        for row in waiting:
            call = row["call"]
            text = rec.text(call)
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
                print(f"No answer for {call}; it stays waiting.", file=out)
        if once:
            return answered
        time.sleep(poll)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="oathline-guard approve")
    ap.add_argument("--server", required=True)
    ap.add_argument("--home", default=os.path.join(os.path.expanduser("~"), ".oathline-guard"))
    ap.add_argument("--once", action="store_true", help="answer what is waiting now, then exit")
    a = ap.parse_args(argv)
    folder = os.path.join(a.home, a.server)
    if not os.path.isfile(os.path.join(folder, "guard.db")):
        print(f"oathline-guard approve: no guard record for server {a.server!r} in {a.home} (start the guard with --human first)",
              file=sys.stderr)
        return 2
    rec = Record(folder, a.server)
    try:
        if not rec.human:
            print("oathline-guard approve: the guard was started without --human: nobody can answer", file=sys.stderr)
            return 2
        try:
            window(rec, ask=lambda prompt, call: input(prompt), out=sys.stdout, once=a.once)
        except NotATerminal as exc:
            print(f"oathline-guard approve: refused: {exc}", file=sys.stderr)
            return 2
        except (KeyboardInterrupt, EOFError):
            print("", file=sys.stdout)
        return 0
    finally:
        rec.close()
