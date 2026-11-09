"""fix-fs: the fix session's only file-writing tool, run behind oathline-guard (SITE_WATCH_PLAN section 2.3, W5).

    python examples/fix_path/fix_fs.py --root <the site's working copy>

read_file and list_directory are reads (on the guard's read list). edit_file(path, old_text, new_text) is the only write: one
exact replacement per call, `old_text` must occur exactly once, the path must stay inside the root. The arguments are flat
strings so the guard's window shows each verbatim (one line when short; a gutter block when multi-line or long), and the
file then holds exactly the shown new text. No create, delete, move or whole-file write exists.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _mcp import schema, serve  # noqa: E402

_STR = {"type": "string"}
TOOLS = [
    {"name": "read_file", "description": "Read one text file of the site.", "inputSchema": schema({"path": _STR}, ["path"])},
    {"name": "list_directory", "description": "List a folder of the site.", "inputSchema": schema({"path": _STR})},
    {"name": "edit_file", "description": "Replace one exact text in one file of the site.",
     "inputSchema": schema({"path": _STR, "old_text": _STR, "new_text": _STR}, ["path", "old_text", "new_text"])},
]


class Files:
    def __init__(self, root):
        self.root = os.path.realpath(root)

    def resolve(self, rel):
        p = os.path.realpath(os.path.join(self.root, str(rel or ".")))
        if p != self.root and not p.startswith(self.root + os.sep):
            raise ValueError(f"{rel!r} is outside the site")
        return p

    def call(self, tool, args):
        if tool == "list_directory":
            return json.dumps(sorted(os.listdir(self.resolve(args.get("path"))))), False
        path = self.resolve(args.get("path"))
        with open(path, encoding="utf-8", newline="") as fh:
            text = fh.read()
        if tool == "read_file":
            return text, False
        old, new = str(args.get("old_text") or ""), str(args.get("new_text") or "")
        n = text.count(old) if old else 0
        if n != 1:
            return f"not changed: old_text occurs {n} times in {args.get('path')} (it must occur exactly once)", True
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text.replace(old, new, 1))
        return f"edited {args.get('path')}: 1 replacement", False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fix-fs")
    ap.add_argument("--root", required=True)
    a = ap.parse_args(argv)
    return serve("fix-fs", TOOLS, Files(a.root).call)


if __name__ == "__main__":
    sys.exit(main())
