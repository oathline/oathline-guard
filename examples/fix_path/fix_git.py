"""fix-git: Stage 1 of the fix path's ladder (SITE_WATCH_PLAN section 2.5): a branch, a commit, a push of that BRANCH and a pull
request, each run once after a person's yes through oathline-guard (W5).

    FIX_PR_API=<url> FIX_PR_TOKEN=<token> FIX_GIT_NAME=<name> FIX_GIT_EMAIL=<email> \
        python examples/fix_path/fix_git.py --repo <working copy> --base main --remote origin

Reads (on the guard's read list): git_status, git_diff. Held: git_commit(branch, message, files) (switches to the branch,
created from the current state if new, and commits EXACTLY the named files, which the window shows; it refuses when anything
else is modified or untracked, so nothing unshown is committed: FABLE 11:42 (1)); git_push(branch, commit) (pushes exactly that commit to that branch; the
branch's head must BE that commit, so the thing pushed is the thing approved; never the base branch; never forced: git refuses
a non-fast-forward by itself); open_pr(branch, title, body) (one POST to FIX_PR_API with the server's own token, never an
argument; no redirect is followed, so the token never goes to another host: FABLE 11:42 (2)). The base branch is protected
in any spelling (refs/heads/, case), and so is the branch the remote's HEAD names. There is no force, no delete, no merge and no
tag tool: stage 2 and 3 are not granted here. The remote's own protected-branch rule is the second line of defence.
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _mcp import schema, serve  # noqa: E402

_STR = {"type": "string"}
TOOLS = [
    {"name": "git_status", "description": "The working copy's status.", "inputSchema": schema({})},
    {"name": "git_diff", "description": "The uncommitted changes.", "inputSchema": schema({})},
    {"name": "git_commit", "description": "Commit exactly these files on a work branch.",
     "inputSchema": schema({"branch": _STR, "message": _STR, "files": {"type": "array", "items": _STR}},
                           ["branch", "message", "files"])},
    {"name": "git_push", "description": "Push exactly this commit to this work branch.",
     "inputSchema": schema({"branch": _STR, "commit": _STR}, ["branch", "commit"])},
    {"name": "open_pr", "description": "Open a pull request from a work branch.",
     "inputSchema": schema({"branch": _STR, "title": _STR, "body": _STR}, ["branch", "title", "body"])},
]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None                                       # a 3xx is an error: the token is never re-sent elsewhere


_OPEN = urllib.request.build_opener(_NoRedirect).open


def _norm(branch: str) -> str:
    b = str(branch or "").strip()
    return (b[len("refs/heads/"):] if b.lower().startswith("refs/heads/") else b).casefold()


class Git:
    def __init__(self, repo, base, remote):
        self.repo, self.base, self.remote = repo, base, remote

    def protected(self) -> set:
        names = {_norm(self.base)}
        head = self.run("symbolic-ref", "--quiet", f"refs/remotes/{self.remote}/HEAD", check=False)
        if head:
            names.add(_norm(head.rsplit("/", 1)[-1]))
        return names

    def run(self, *args, check=True):
        p = subprocess.run(["git", "-c", "core.autocrlf=false", *args], cwd=self.repo, capture_output=True, text=True,
                           encoding="utf-8")
        if check and p.returncode:
            raise RuntimeError(f"git {args[0]}: {p.stderr.strip()[:300]}")
        return p.stdout.strip()

    def work_branch(self, branch):
        b = str(branch or "")
        if _norm(b) in self.protected():
            raise ValueError(f"{b!r} is the base branch: it is never committed to or pushed from here")
        if subprocess.run(["git", "check-ref-format", "--branch", b], cwd=self.repo, capture_output=True).returncode:
            raise ValueError(f"{b!r} is not a branch name")
        return b

    def call(self, tool, args):
        if tool == "git_status":
            return self.run("status", "--porcelain=v1", "-b"), False
        if tool == "git_diff":
            return self.run("diff"), False
        try:
            branch = self.work_branch(args.get("branch"))
        except ValueError as e:
            return f"refused: {e}", True
        if tool == "git_commit":
            files = args.get("files")
            if not isinstance(files, list) or not files or not all(isinstance(f, str) and f for f in files):
                return "refused: name the files to commit (a list of paths)", True
            wanted = {f.replace("\\", "/") for f in files}
            raw = subprocess.run(["git", "status", "--porcelain=v1", "-z", "-uall"], cwd=self.repo, capture_output=True,
                                 text=True, encoding="utf-8").stdout          # not stripped: each entry is "XY path"
            entries, changed = raw.split("\0"), set()
            i = 0
            while i < len(entries):
                e = entries[i]
                if len(e) > 3:
                    changed.add(e[3:])
                    if e[0] in "RC":                     # a rename / copy: the next entry is its source path
                        i += 1
                        changed.add(entries[i]) if i < len(entries) and entries[i] else None
                i += 1
            extra = sorted(changed - wanted)
            if extra:                                     # checked BEFORE any branch is made or switched
                return f"refused: other changes in the working copy, not shown in this call: {', '.join(extra)}", True
            current = self.run("rev-parse", "--abbrev-ref", "HEAD")
            if current != branch:
                exists = not self.run("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False) == ""
                self.run("switch", branch) if exists else self.run("switch", "-c", branch)
            self.run("add", "--", *sorted(wanted))
            if not self.run("diff", "--cached", "--name-only"):
                return "nothing to commit", True
            name = os.environ.get("FIX_GIT_NAME") or "fix session"
            email = os.environ.get("FIX_GIT_EMAIL") or "fix@example.invalid"
            self.run("-c", f"user.name={name}", "-c", f"user.email={email}", "commit", "-q", "-m", str(args.get("message")))
            sha = self.run("rev-parse", "HEAD")
            files = self.run("show", "--name-only", "--format=", sha).splitlines()
            return json.dumps({"branch": branch, "commit": sha, "files": files}), False
        if tool == "git_push":
            want = str(args.get("commit") or "")
            head = self.run("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False)
            if not want or head != want:
                return f"refused: {branch!r} is at {head or 'nothing'}, not the approved commit {want}", True
            self.run("push", "-q", self.remote, f"{want}:refs/heads/{branch}")
            return json.dumps({"pushed": branch, "commit": want}), False
        if tool == "open_pr":
            url, token = os.environ.get("FIX_PR_API"), os.environ.get("FIX_PR_TOKEN")
            if not url or not token:
                return "refused: no pull-request API or token configured for this server", True
            body = json.dumps({"head": branch, "base": self.base, "title": str(args.get("title")),
                               "body": str(args.get("body"))}).encode("utf-8")
            req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json",
                                                                                "Authorization": f"Bearer {token}"})
            try:
                resp = _OPEN(req, timeout=20)
            except urllib.error.HTTPError as e:
                return f"the pull-request API answered {e.code}; nothing followed", True
            with resp:
                answer = json.loads(resp.read().decode("utf-8") or "{}")
            return json.dumps({"pr": answer.get("number"), "url": answer.get("url")}), False
        return f"unknown tool {tool}", True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fix-git")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--base", default="main")
    ap.add_argument("--remote", default="origin")
    a = ap.parse_args(argv)
    return serve("fix-git", TOOLS, Git(a.repo, a.base, a.remote).call)


if __name__ == "__main__":
    sys.exit(main())
