#!/usr/bin/env python3
"""The squad's seal: a record that one exact commit was verified with SHIP.

    squad-seal record --card <id> --model <name> --verdict SHIP --evidence <path>
        run inside the card's worktree; seals HEAD. Refuses a dirty worktree and
        any verdict other than SHIP.
    squad-seal show [sha]
        prints the seal of the SHA (HEAD by default); exit 1 if there is none.

A seal is a JSON file, mode 0600, at
~/.claude/squad/seals/<hash of the git common dir>/<sha>.json with repo, branch,
sha, card, at, model, verdict and evidence. With the seal on in a repository
(`git config squad.seal true`, or SQUAD_SEAL=1), squad-watch lets a PR merge
through only if the PR head has a seal, and a push to the trunk only if the
pushed SHA has one.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

BASE = os.path.join(os.path.expanduser("~"), ".claude", "squad")
SEALS = os.path.join(BASE, "seals")


def git(*args):
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
        return r.returncode, r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def folder():
    rc, repo = git("rev-parse", "--path-format=absolute", "--git-common-dir")
    if rc != 0 or not repo:
        return "", ""
    repo = os.path.realpath(repo)
    return repo, os.path.join(SEALS, hashlib.sha1(repo.encode()).hexdigest()[:16])


def record(a):
    repo, where = folder()
    if not repo:
        print("squad-seal: this is not a git repository. Run it inside the card's worktree.", file=sys.stderr)
        return 2
    if a.verdict != "SHIP":
        print(f"squad-seal: the verdict is {a.verdict!r}; only SHIP is sealed. Fix what the verifier "
              "returned and send the card back to it.", file=sys.stderr)
        return 1
    _, dirty = git("status", "--porcelain")
    if dirty:
        files = [f.split(None, 1)[-1] for f in dirty.splitlines()]
        print("squad-seal: the worktree is dirty (" + ", ".join(files[:8]) + (" ..." if len(files) > 8 else "")
              + "). The seal covers a commit: commit or clean these, have the verifier review that commit, "
              "then seal it.", file=sys.stderr)
        return 1
    if not os.path.isfile(a.evidence):
        print(f"squad-seal: evidence {a.evidence} is not a file.", file=sys.stderr)
        return 1
    _, sha = git("rev-parse", "HEAD")
    _, branch = git("branch", "--show-current")
    seal = {"repo": repo, "branch": branch, "sha": sha, "card": a.card,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "model": a.model,
            "verdict": a.verdict, "evidence": os.path.realpath(a.evidence)}
    os.makedirs(where, mode=0o700, exist_ok=True)
    path = os.path.join(where, f"{sha}.json")
    tmp = f"{path}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(seal, fh, indent=1)
    os.replace(tmp, path)
    print(f"sealed {sha[:12]} ({branch or 'detached'}, card {a.card}) -> {path}")
    return 0


def show(a):
    repo, where = folder()
    if not repo:
        print("squad-seal: this is not a git repository.", file=sys.stderr)
        return 2
    rc, sha = git("rev-parse", "--verify", "-q", f"{a.sha or 'HEAD'}^{{commit}}")
    path = os.path.join(where, f"{sha}.json")
    if rc != 0 or not os.path.isfile(path):
        print(f"squad-seal: no seal for {sha[:12] or a.sha}.", file=sys.stderr)
        return 1
    with open(path, encoding="utf-8") as fh:
        print(fh.read())
    return 0


def main():
    p = argparse.ArgumentParser(prog="squad-seal", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record", help="seal HEAD of this worktree")
    for flag in ("--card", "--model", "--verdict", "--evidence"):
        r.add_argument(flag, required=True)
    s = sub.add_parser("show", help="show the seal of a SHA (HEAD by default)")
    s.add_argument("sha", nargs="?", default="")
    a = p.parse_args()
    os.umask(0o077)
    return record(a) if a.cmd == "record" else show(a)


if __name__ == "__main__":
    sys.exit(main())
