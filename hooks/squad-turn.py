#!/usr/bin/env python3
"""The squad's merge turn: one merge call at a time per repository.

    squad-turn request [PR]   records an intent to merge (it blocks nobody)
    squad-turn release        drops your intent, or gives back a turn you hold
    squad-turn status         who is merging right now, the intents, and your branch against the trunk

The turn covers only the merge call itself: squad-watch takes it in the
PreToolUse of the merge and gives it back in the PostToolUse of the same call,
success or failure; a turn held longer than SQUAD_TURN_HOLD (120 s) expires.
Before a PR merge the watcher test-merges the PR head into the fetched base and,
with the seal on, checks the seal (see squad-seal). The rules are in the header
of squad-watch.py.
"""
import hashlib
import json
import os
import subprocess
import sys
import time

BASE = os.path.join(os.path.expanduser("~"), ".claude", "squad")


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
    return (f"session {e['session'][:8]}" + (f" (PR #{e['pr']})" if e.get("pr") else "")
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
    h, intents = d.get("holder"), d.get("intents") or []
    print(f"Merge turn of {repo}")
    print("  merging now: " + (f"{line(h)}  (for {int(time.time() - h['since'])} s)" if h
                               else "nobody — the next merge goes through"))
    for i, e in enumerate(intents, 1):
        print(f"  intent {i}. {line(e)}  (asked {age(e['asked'])} ago)")
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
        for e in ([h] if h else []) + intents:
            if e.get("branch") and e["branch"] != mine:
                _, other = git("diff", "--name-only", f"{base}...{e['branch']}")
                both = sorted(own & set(other.splitlines()))
                if both:
                    print(f"  in common with {e['branch']}: " + ", ".join(both[:8]))
    if os.environ.get("SQUAD_WATCH") == "0" or os.environ.get("SQUAD_TURN") == "0":
        print("  (the merge turn is turned off by an environment variable: nothing was recorded)")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] and a[0] not in ("request", "release", "status"):
        print(__doc__)
        sys.exit(2)
    sys.exit(status())
