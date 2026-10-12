#!/usr/bin/env python3
"""The squad's merge queue: the turn to land on main, one session per repository.

    squad-turn request [PR]   requests the turn (or joins the queue) for this session
    squad-turn release        gives the turn back, or leaves the queue
    squad-turn status         who holds the turn, the queue, and what your branch contends for

The request is recorded by squad-watch, in the PreToolUse of this very call (it
is the one that knows which session is talking); this script only shows the
state. The turn is also requested automatically on the first `gh pr merge`.
The rules are in the header of squad-watch.py.

    squad-turn call <pane> <session>   (used by the watcher) wakes up the session whose turn it is
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time

BASE = os.path.join(os.path.expanduser("~"), ".claude", "squad")
HERDR = os.environ.get("HERDR_BIN_PATH") or "herdr"
CALL = ("[squad-watch] MERGE TURN: it is this session's turn in the merge queue. Run `squad-turn status` "
        "and, if the turn is yours, sync with main once, run the suite and merge the PR.")


def git(*args, cwd=None):
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True, timeout=10, cwd=cwd,
                           stdin=subprocess.DEVNULL)
        return r.returncode, r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def age(ts):
    return f"{int((time.time() - ts) / 60)} min"


def line(e):
    return (f"session {e['session'][:8]}" + (f"  PR #{e['pr']}" if e.get("pr") else "")
            + (f"  {e['branch']}" if e.get("branch") else ""))


def status():
    rc, repo = git("rev-parse", "--path-format=absolute", "--git-common-dir")
    if rc != 0 or not repo:
        print("squad-turn: this is not a git repository.")
        return 1
    repo = os.path.realpath(repo)
    path = os.path.join(BASE, "turn", hashlib.sha1(repo.encode()).hexdigest()[:16] + ".json")
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        d = {}
    h, queue = d.get("holder"), d.get("queue") or []
    print(f"Merge queue of {repo}")
    print("  holding the turn: " + (f"{line(h)}  (for {age(h['since'])})" if h else "nobody — the next merge goes through"))
    for i, e in enumerate(queue, 1):
        print(f"  {i}. {line(e)}  (waiting for {age(e['asked'])})")
    last = d.get("last")
    if last:
        print(f"  last: session {last['session'][:8]}" + (f" PR #{last['pr']}" if last.get("pr") else "")
              + f" — {last['why']}, {age(last['at'])} ago")
    _, mine = git("branch", "--show-current")
    base = next((b for b in ("origin/main", "origin/master")
                 if git("rev-parse", "--verify", "-q", b)[0] == 0), "")
    if mine and base:
        rc, out = git("merge-tree", "--write-tree", "--name-only", base, mine)
        if rc == 1:
            files = [f for f in out.splitlines()[1:] if f and not f.startswith(("Auto-", "CONFLICT"))]
            print(f"  {mine} x {base} (local ref, no fetch): CONFLICT in " + ", ".join(files[:8]))
        elif rc == 0:
            print(f"  {mine} x {base} (local ref, no fetch): merges without conflict")
        _, own = git("diff", "--name-only", f"{base}...{mine}")
        own = set(own.splitlines())
        for e in ([h] if h else []) + queue:
            if e.get("branch") and e["branch"] != mine:
                _, other = git("diff", "--name-only", f"{base}...{e['branch']}")
                both = sorted(own & set(other.splitlines()))
                if both:
                    print(f"  in common with {e['branch']}: " + ", ".join(both[:8]))
    if os.environ.get("SQUAD_WATCH") == "0" or os.environ.get("SQUAD_TURN") == "0":
        print("  (the queue is turned off by an environment variable: nothing was recorded)")
    return 0


def agent(pane):
    try:
        r = subprocess.run([HERDR, "agent", "get", pane], capture_output=True, text=True, timeout=15)
        a = json.loads(r.stdout)["result"]["agent"]
        return (a.get("agent_session") or {}).get("value") or "", a.get("agent_status") or ""
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
        return "", ""


def call(pane, session):
    """Wakes up the session whose turn it is, if the pane is still its own and
    it is idle. A working session gets the message from the watcher itself, on
    the next PostToolUse."""
    if not re.fullmatch(r"[A-Za-z0-9:_-]{1,40}", pane) or not re.fullmatch(r"[0-9a-f-]{8,64}", session):
        return 2
    time.sleep(2)
    sid, state = agent(pane)
    if sid != session or state in ("working", "blocked"):
        return 1
    try:
        return subprocess.run([HERDR, "agent", "prompt", pane, CALL], capture_output=True,
                              timeout=20).returncode
    except (OSError, subprocess.TimeoutExpired):
        return 1


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["call"] and len(a) == 3:
        sys.exit(call(a[1], a[2]))
    if a[:1] and a[0] not in ("request", "release", "status"):
        print(__doc__)
        sys.exit(2)
    sys.exit(status())
