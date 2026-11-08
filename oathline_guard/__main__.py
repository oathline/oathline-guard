"""python -m oathline_guard run ... | approve ... (approve from G4)."""
import sys


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: python -m oathline_guard run --server NAME [--reads READS.json] [--home DIR] -- <server command ...>")
        return 0 if argv else 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "run":
        from .guard import run
        return run(rest)
    print(f"oathline-guard: unknown command {cmd!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
