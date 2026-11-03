#!/usr/bin/env python3
"""Board heartbeat: says what is stuck between sessions, and nothing otherwise.

    heartbeat.py [--repo PATH]... [--handoffs DIR]... [--hours 9-19]
                 [--card-days 3] [--pr-hours 24] [--worktree-days 7] [--handoff-days 7]

Five checks, read-only. Each finding is ONE line: the check, the subject, what
is stuck, and "Next:" with who acts and the command. With nothing stuck it
prints nothing and exits 0, so a scheduled run stays silent. Names read from
the board, GitHub or disk are stripped of control characters and JSON-quoted
when not plain; titles are not printed; a "Next:" command holds only values
this script validated (an integer PR number, a hex card id, a path that exists).

    stale-card     cards in a working step of the AgenFK board (`agenfk list --all
                   --active --json`, TODO left out) with no change for > --card-days;
                   one line per project
    pr-no-review   open, non-draft PRs (`gh pr list`) with no review at all, opened
                   more than --pr-hours ago; one line per repository with a GitHub remote
    merge-turn     a merge turn (~/.claude/squad/turn/*.json, the watcher's queue) held
                   for longer than SQUAD_TURN_MAX seconds (default 3600), or a queue
                   with nobody holding the turn; one line per repository
    idle-worktree  linked worktrees with no commit, checkout or claim for
                   > --worktree-days, and worktrees registered but missing on disk;
                   one line per repository
    old-handoff    handoff files (*.md) older than --handoff-days in ~/.claude/handoffs,
                   ~/.claude/squad/handoffs and <repo>/.claude/handoffs; one line per directory

Repositories: every --repo, or else the project roots the AgenFK board knows
(`agenfk list-projects --json`) plus the repository of the current directory.
A missing `agenfk`, `gh` or `git` skips its check with one line saying so.
--hours START-END (local time, END exclusive, may wrap past midnight) makes a run
outside those hours print nothing: a catch-up run at 23:00 stays quiet.

A value that does not parse (a timestamp that is not a finite number, a project
root that is not a string) drops that one finding; a check that still breaks
prints one "skipped <check>" line and the other checks run: never a traceback.

Acts on nothing: no card moves, no merges, no messages. Standard library only.
"""
import argparse
import datetime
import glob
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import unicodedata

HOME = os.path.expanduser("~")
TURN = os.path.join(HOME, ".claude", "squad", "turn")          # same directory as hooks/squad-watch.py
HANDOFF_DIRS = [os.path.join(HOME, ".claude", "squad", "handoffs"), os.path.join(HOME, ".claude", "handoffs")]
NOT_WORKING = {"TODO", "DONE", "BLOCKED", "PAUSED", "DEFERRED", "ARCHIVED", "TRASHED", "CANCELLED"}
DAY = 86400


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def short(path):
    path = str(path)
    return "~" + path[len(HOME):] if HOME and HOME != "/" and (path == HOME or path.startswith(HOME + os.sep)) else path


# ---- untrusted text ---------------------------------------------------------
# A model session reads these lines. PR titles (anyone can open a PR on a public
# repo), card titles, file names, paths and repo names are not ours: a "\n",
# "\r" or "\x1b" in one would forge a line or an action. Every interpolated field
# goes through clean(); a name that is not plain goes out JSON-quoted (data, not
# words of the line); a "Next:" command carries only values validated here.
# Titles are left out altogether: quoting stops a forged line, not a sentence
# addressed to the model, and the id in the command is enough to find the item.

SAFE = re.compile(r"[\w.@+/~-]+", re.ASCII)
PATH_OK = re.compile(r"[\w.@+/~ ,=-]+")
CARD_ID = re.compile(r"[0-9a-fA-F]{8}(?:-?[0-9a-fA-F]{4}){3}-?[0-9a-fA-F]{12}|[0-9a-fA-F]{8,40}")
SESSION_ID = re.compile(r"[0-9A-Za-z_-]{1,64}")
STATUS = re.compile(r"[A-Z_]{1,24}")


def clean(text, width=60):
    """One printable line, at most `width` long: control and non-printing characters
    (Unicode C*: \\n \\r \\t \\x1b, bidi overrides, ...) and line/paragraph separators
    become spaces, runs of space collapse to one."""
    text = "".join(" " if unicodedata.category(ch)[0] == "C" or unicodedata.category(ch) in ("Zl", "Zp") else ch
                   for ch in str("" if text is None else text))
    text = " ".join(text.split())
    return text if len(text) <= width else text[:width - 1] + "…"


def label(text, width=40):
    """A name for the subject of a line: bare when it is plain, JSON-quoted otherwise."""
    text = clean(text, width)
    return text if SAFE.fullmatch(text) else json.dumps(text, ensure_ascii=False)


def quoted(text, width=80):
    """Free text (an error message) as a JSON string: always data."""
    return json.dumps(clean(text, width), ensure_ascii=False)


def pr_number(value):
    """A PR number as an int, or None: an int (not a bool) or a string of digits."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 9:
        return int(value) or None
    return None


def card_id(value):
    """The first 8 characters of a hex/uuid card id, or None."""
    value = value if isinstance(value, str) else ""
    return value[:8].lower() if CARD_ID.fullmatch(value) else None


def shell_path(path):
    """A path fit for a command: it exists, holds only letters, digits, space and
    `._@+/~,=-` (no `;`, `:`, quotes, `$`, control characters), and is shell-quoted
    (`~/` kept outside the quotes so the shell still expands it). None otherwise."""
    path = str(path or "")
    if not path or not PATH_OK.fullmatch(path) or not os.path.exists(path):
        return None
    shown = short(path)
    if shown.startswith("~/"):
        return "~/" + shlex.quote(shown[2:])
    return "~" if shown == "~" else shlex.quote(shown)


def finite(value):
    """A real, finite number as a float (not a bool, not NaN or +-Infinity), or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def ago(seconds):
    seconds = finite(seconds)
    if seconds is None or seconds < 0:
        return "?"
    if seconds >= 2 * DAY:
        return f"{int(seconds // DAY)}d"
    if seconds >= 2 * 3600:
        return f"{int(seconds // 3600)}h"
    return f"{int(seconds // 60)} min"


def when(stamp):
    """Epoch seconds of an ISO 8601 stamp (`...Z` included); None if unreadable."""
    try:
        d = datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return d.timestamp()


def run(cmd, cwd=None, timeout=30):
    """(returncode, stdout, first line of stderr). Raises nothing: an error is returncode 127/124."""
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, ValueError):
        return 127, "", "could not run"
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"
    err = next((ln.strip() for ln in r.stderr.splitlines() if ln.strip()), "")
    return r.returncode, r.stdout, err


def load_json(text):
    try:
        return json.loads(text)
    except ValueError:
        return None


def git_common_dir(path):
    rc, out, _ = run(["git", "-C", path, "rev-parse", "--path-format=absolute", "--git-common-dir"], timeout=10)
    return os.path.realpath(out.strip()) if rc == 0 and out.strip() else ""


def repo_name(common):
    """`/x/demo/.git` -> `demo`; a bare `/x/demo.git` -> `demo.git`."""
    common = common.rstrip(os.sep)
    return os.path.basename(os.path.dirname(common)) if os.path.basename(common) == ".git" else os.path.basename(common)


# ---- 1. cards ---------------------------------------------------------------

def check_cards(projects, days, now):
    if not shutil.which("agenfk"):
        return ["skipped stale-card: agenfk not found on PATH, the board was not read."]
    rc, out, err = run(["agenfk", "list", "--all", "--active", "--json"])
    items = load_json(out) if rc == 0 else None
    if not isinstance(items, list):
        why = f"exit {rc}" + (f": {quoted(err)}" if err else "") if rc else "the output is not a JSON list"
        return [f"skipped stale-card: `agenfk list --all --active --json` failed ({why}). "
                "Next: owner checks the board server: agenfk health"]
    names = {str(p.get("id")): p.get("name") for p in projects if isinstance(p, dict)}
    stale = {}
    for it in items:
        if not isinstance(it, dict) or str(it.get("status", "")).upper() in NOT_WORKING:
            continue
        t = when(it.get("updatedAt") or it.get("createdAt"))
        if t is not None and now - t > days * DAY:
            stale.setdefault(str(it.get("projectId") or ""), []).append((t, it))
    lines = []
    for pid, found in sorted(stale.items(), key=lambda kv: str(names.get(kv[0]) or kv[0])):
        t, old = min(found, key=lambda f: f[0])
        cid = card_id(old.get("id"))
        status = str(old.get("status") or "").upper()
        status = status if STATUS.fullmatch(status) else "?"
        name = label(names.get(pid)) if names.get(pid) else "project " + (label(pid[:8]) if pid else "?")
        oldest = f"oldest {cid} ({status}, {ago(now - t)})" if cid else f"oldest ({status}, {ago(now - t)})"
        nxt = (f"Next: main session resumes or parks it: agenfk get {cid}" if cid else
               "Next: main session reads the board: agenfk list --all --active")
        lines.append(f"stale-card {name}: {len(found)} card(s) in a working step with no change for "
                     f"> {days}d, {oldest}. {nxt}")
    return lines


# ---- 2. pull requests -------------------------------------------------------

def github_remote(repo):
    rc, out, _ = run(["git", "-C", repo, "remote", "-v"], timeout=10)
    return rc == 0 and "github.com" in out


def check_prs(repos, hours, now):
    targets = [r for r in repos if github_remote(r["top"])]
    if not targets:
        return []
    if not shutil.which("gh"):
        return ["skipped pr-no-review: gh not found on PATH, the pull requests were not read."]
    lines = []
    for r in targets:
        rc, out, err = run(["gh", "pr", "list", "--state", "open", "--limit", "100",
                            "--json", "number,title,isDraft,createdAt,latestReviews"], cwd=r["top"])
        prs = load_json(out) if rc == 0 else None
        if not isinstance(prs, list):
            why = f"exit {rc}" + (f": {quoted(err)}" if err else "") if rc else "the output is not a JSON list"
            lines.append(f"skipped pr-no-review {label(r['name'])}: `gh pr list` failed ({why}). Next: owner "
                         "checks the login: gh auth status")
            continue
        waiting = []
        for p in prs:
            if not isinstance(p, dict) or p.get("isDraft") or p.get("latestReviews"):
                continue
            t = when(p.get("createdAt"))
            if t is not None and now - t > hours * 3600:
                waiting.append((t, p))
        if waiting:
            t, old = min(waiting, key=lambda w: w[0])
            num = pr_number(old.get("number"))
            oldest = f"oldest #{num} ({ago(now - t)})" if num else f"oldest ({ago(now - t)})"
            nxt = (f"Next: main session dispatches the verifier on it: gh pr view {num}" if num else
                   "Next: main session dispatches the verifier on them: gh pr list --state open")
            lines.append(f"pr-no-review {label(r['name'])}: {len(waiting)} open PR(s) with no review for > {hours}h, "
                         f"{oldest}. {nxt}")
    return lines


# ---- 3. merge turn ----------------------------------------------------------

def check_turn(turn_max, now):
    lines = []
    for path in sorted(glob.glob(os.path.join(TURN, "*.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict):
            continue
        repo = str(d.get("repo") or "")
        name = label(repo_name(repo) if repo else os.path.basename(path))
        queue = d.get("queue") if isinstance(d.get("queue"), list) else []
        holder, queue = d.get("holder"), [e for e in queue if isinstance(e, dict)]
        waiting = f", {len(queue)} waiting" if queue else ""
        settle = ("Next: any session in that repository runs squad-turn status (the watcher settles a stale "
                  "turn), or the holder gives it back: squad-turn release")
        if isinstance(holder, dict):
            since = finite(holder.get("since"))
            if since is not None and now - since > turn_max:
                session = holder.get("session")
                session = session[:8] if isinstance(session, str) and SESSION_ID.fullmatch(session[:8]) else "?"
                num = pr_number(holder.get("pr"))
                who = f"session {session}" + (f" (PR #{num})" if num else "")
                lines.append(f"merge-turn {name}: {who} has held the merge turn for {ago(now - since)} "
                             f"(max {ago(turn_max)}){waiting}. {settle}")
        elif queue:
            asked = min((finite(e.get("asked")) for e in queue if finite(e.get("asked")) is not None), default=None)
            held = f" for {ago(now - asked)}" if asked is not None else ""
            lines.append(f"merge-turn {name}: nobody holds the turn but {len(queue)} session(s) wait{held}. {settle}")
    return lines


# ---- 4. worktrees -----------------------------------------------------------

def worktree_gitdir(path):
    try:
        with open(os.path.join(path, ".git"), encoding="utf-8") as fh:
            head = fh.read(4096).strip()
    except OSError:
        return ""
    if not head.startswith("gitdir:"):
        return ""
    gd = head[len("gitdir:"):].strip()
    return gd if os.path.isabs(gd) else os.path.normpath(os.path.join(path, gd))


def reflog_time(gd):
    """Time written in the last entry of the worktree's HEAD reflog (commit, checkout, reset).
    The entry, not the file's mtime: `git gc` rewrites every reflog and would make all look busy."""
    try:
        with open(os.path.join(gd, "logs", "HEAD"), "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 4096))
            last = fh.read().decode("utf-8", "replace").rstrip("\n").rsplit("\n", 1)[-1]
        return finite(float(last.split("\t", 1)[0].rsplit(" ", 2)[-2]))
    except (OSError, ValueError, IndexError):
        return None


def last_activity(path):
    """Newest of: the last HEAD reflog entry, the index, HEAD, the writer's claim."""
    gd = worktree_gitdir(path)
    if not gd:
        return None
    stamps = [reflog_time(gd)]
    for f in ("index", "HEAD", "squad-claim"):
        try:
            stamps.append(os.path.getmtime(os.path.join(gd, f)))
        except OSError:
            pass
    stamps = [s for s in stamps if s is not None]
    return max(stamps) if stamps else None


def check_worktrees(repos, days, now):
    lines = []
    for r in repos:
        rc, out, err = run(["git", "-C", r["top"], "worktree", "list", "--porcelain"], timeout=15)
        if rc != 0:
            continue
        entries, cur = [], None
        for ln in out.splitlines():
            if ln.startswith("worktree "):
                cur = {"path": ln[len("worktree "):]}
                entries.append(cur)
            elif cur is not None and ln.split(" ", 1)[0] in ("bare", "prunable"):
                cur[ln.split(" ", 1)[0]] = True
        idle, missing = [], 0
        for e in entries[1:]:                       # the first entry is the main worktree
            if e.get("prunable") or not os.path.isdir(e["path"]):
                missing += 1
                continue
            t = last_activity(e["path"])
            if t is not None and now - t > days * DAY:
                idle.append((t, e["path"]))
        if not idle and not missing:
            continue
        parts, nxt = [], []
        top = shell_path(r["top"])
        listing = f"git -C {top} worktree list" if top else "git worktree list in that repository"
        if idle:
            t, path = min(idle)
            where = shell_path(path)
            parts.append(f"{len(idle)} worktree(s) with no commit, checkout or claim for > {days}d, "
                         f"oldest {where or label(short(path), 80)} ({ago(now - t)})")
            nxt.append(f"github agent confirms the branch is merged or parked, then git worktree remove {where}"
                       if where else f"github agent confirms each branch is merged or parked: {listing}")
        if missing:
            parts.append(f"{missing} registered but missing on disk")
            nxt.append(f"git -C {top} worktree prune" if top else f"github agent checks: {listing}")
        lines.append(f"idle-worktree {label(r['name'])}: " + "; ".join(parts) + ". Next: " + "; ".join(nxt))
    return lines


# ---- 5. handoffs ------------------------------------------------------------

def check_handoffs(dirs, days, now):
    lines = []
    for d in dirs:
        old = []
        for path in glob.glob(os.path.join(d, "*.md")):
            try:
                t = os.path.getmtime(path)
            except OSError:
                continue
            if now - t > days * DAY:
                old.append((t, path))
        if old:
            t, path = min(old)
            where = shell_path(d)
            nxt = (f"Next: context agent picks up what is still open and archives the rest: ls -t {where}" if where
                   else "Next: context agent picks up what is still open in that directory and archives the rest")
            lines.append(f"old-handoff {label(short(d), 80)}: {len(old)} handoff(s) older than {days}d, oldest "
                         f"{label(os.path.basename(path), 60)} ({ago(now - t)}). {nxt}")
    return lines


# ---- main -------------------------------------------------------------------

def in_hours(spec, hour):
    a, b = (int(x) for x in spec.split("-", 1))
    if not (0 <= a <= 23 and 0 <= b <= 24):
        raise ValueError(spec)
    return a <= hour < b if a <= b else (hour >= a or hour < b)


def hours_arg(spec):
    try:
        in_hours(spec, 0)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected START-END in local hours, such as 9-19; got {spec!r}")
    return spec


def board_projects():
    if not shutil.which("agenfk"):
        return []
    rc, out, _ = run(["agenfk", "list-projects", "--json"])
    d = load_json(out) if rc == 0 else None
    return [p for p in d if isinstance(p, dict)] if isinstance(d, list) else []


def find_repos(paths):
    seen, repos = set(), []
    for p in paths:
        if not isinstance(p, str) or not p or not os.path.isdir(p):
            continue
        common = git_common_dir(p)
        if not common or common in seen:
            continue
        seen.add(common)
        top = os.path.dirname(common) if os.path.basename(common) == ".git" else common
        repos.append({"common": common, "top": top if os.path.isdir(top) else p, "name": repo_name(common)})
    return sorted(repos, key=lambda r: r["name"])


def guarded(lines, check, fn, *args):
    """fn(*args), or [] plus one "skipped" line in `lines` if it raises: one broken check
    does not take the other checks' lines with it, and nothing prints a traceback."""
    try:
        return fn(*args)
    except Exception as exc:                    # anything: a bug here must not cost the others
        lines.append(f"skipped {check}: the check broke ({type(exc).__name__}), its findings are not shown. "
                     "Next: owner opens an issue naming the check and the error")
        return []


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 epilog="Prints nothing when nothing is stuck. See the module header for each check.")
    ap.add_argument("--repo", action="append", default=[], help="repository to check (repeatable); "
                    "default: the AgenFK project roots plus the current directory's repository")
    ap.add_argument("--handoffs", action="append", default=[], help="extra handoff directory (repeatable)")
    ap.add_argument("--hours", type=hours_arg, help="print nothing outside these local hours, e.g. 9-19")
    ap.add_argument("--card-days", type=int, default=3, help="a card with no change for longer is stale (default 3)")
    ap.add_argument("--pr-hours", type=int, default=24, help="a PR with no review for longer is stuck (default 24)")
    ap.add_argument("--worktree-days", type=int, default=7, help="a worktree with no activity for longer is idle (default 7)")
    ap.add_argument("--handoff-days", type=int, default=7, help="a handoff older than this is old (default 7)")
    a = ap.parse_args(argv)
    if a.hours and not in_hours(a.hours, datetime.datetime.now().hour):
        return 0
    now = time.time()
    lines = []
    projects = guarded(lines, "board-projects", board_projects)
    lines += guarded(lines, "stale-card", check_cards, projects, a.card_days, now)
    if shutil.which("git"):
        roots = a.repo or [p.get("projectRoot") for p in projects] + [os.getcwd()]
        repos = guarded(lines, "repositories", find_repos, roots)
        lines += guarded(lines, "pr-no-review", check_prs, repos, a.pr_hours, now)
    else:
        repos = []
        lines.append("skipped pr-no-review and idle-worktree: git not found on PATH.")
    lines += guarded(lines, "merge-turn", check_turn, env_int("SQUAD_TURN_MAX", 3600), now)
    lines += guarded(lines, "idle-worktree", check_worktrees, repos, a.worktree_days, now)
    dirs = HANDOFF_DIRS + [os.path.join(r["top"], ".claude", "handoffs") for r in repos] + a.handoffs
    lines += guarded(lines, "old-handoff", check_handoffs, list(dict.fromkeys(os.path.realpath(d) for d in dirs)),
                     a.handoff_days, now)
    for ln in lines:
        print(ln)
    return 0


if __name__ == "__main__":
    sys.exit(main())
