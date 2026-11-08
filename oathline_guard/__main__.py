"""python -m oathline_guard run ... | approve ..."""
import sys

USAGE = ("usage: python -m oathline_guard run --server NAME [--reads READS.json] [--home DIR] [--human NAME] [--shown-text] "
         "-- <server command ...>\n"
         "       python -m oathline_guard approve --server NAME [--home DIR] [--once]")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0 if argv else 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "run":
        from .guard import run
        return run(rest)
    if cmd == "approve":
        from .approve import main as approve_main
        return approve_main(rest)
    print(f"oathline-guard: unknown command {cmd!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
