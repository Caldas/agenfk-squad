#!/usr/bin/env python3
"""The squad's heavy review: another model reads the card's diff, read-only, before the PR.

    squad-review --card <id> [--base origin/main]

Run it inside the card's worktree, on the commit you want reviewed. It builds
the diff base...HEAD, reads the card (`agenfk get <id> --json`) for the
acceptance criteria, and asks a different model for a review that ends with
one line `VERDICT: SHIP|FIX_FIRST|REJECT`.

The reviewer:
    default          `codex exec --sandbox read-only`, prompt on stdin, in the worktree
    SQUAD_REVIEWER   a command that reads the prompt on stdin and prints the review,
                     e.g. `claude -p --model <model> --allowedTools Read,Grep,Glob`.
                     It must not write: the script cannot enforce that for you.

The report goes to <git dir of the worktree>/squad-review/<sha>.md, outside
`git status`. It is the evidence for the HEAVY_REVIEW step and for
`squad-seal record`.

Exit code: 0 only for SHIP. 1 for FIX_FIRST or REJECT (back to IMPLEMENT).
2 when there was no review: no reviewer, no card, no diff, a reviewer error or
timeout, or an answer whose last line is not a verdict. A missing verdict is
never read as SHIP.

    SQUAD_REVIEW_TIMEOUT   seconds the reviewer may take (default 1800)
"""
import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

VERDICTS = ("SHIP", "FIX_FIRST", "REJECT")
VERDICT_LINE = re.compile(r"[*_`\s]*VERDICT:[*_`\s]*(SHIP|FIX_FIRST|REJECT)[*_`\s.]*")
MAX_DIFF = 300_000          # characters of diff put in the prompt; the reviewer can read the rest in the worktree


def env_int(name, default):
    try:
        value = int(os.environ.get(name, ""))
        return value if value > 0 else default
    except ValueError:
        return default


def fail(message):
    print(f"squad-review: {message}", file=sys.stderr)
    return 2


def git(*args, cwd=None):
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd,
                           stdin=subprocess.DEVNULL, timeout=60)
        return r.returncode, r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def read_card(card):
    """The card as the reviewer needs it, or None."""
    try:
        r = subprocess.run(["agenfk", "get", card, "--json"], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=60)
        if r.returncode != 0:
            return None
        data = json.loads(r.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("title"):
        return None
    parts = [f"Title: {data['title']}", f"Status: {data.get('status', '')}",
             "", "Description:", data.get("description") or "(none)"]
    if data.get("implementationPlan"):
        parts += ["", "Implementation plan:", data["implementationPlan"]]
    comments = [c.get("content", "") for c in data.get("comments") or [] if isinstance(c, dict)]
    if comments:
        parts += ["", "Comments (later ones refine the description):"] + [f"- {c}" for c in comments]
    return "\n".join(parts)


def reviewer():
    """(argv, label) of the reviewer, or (None, reason)."""
    custom = os.environ.get("SQUAD_REVIEWER", "").strip()
    if custom:
        try:
            argv = shlex.split(custom)
        except ValueError:
            return None, f"SQUAD_REVIEWER is not a valid command line: {custom!r}."
        if not shutil.which(argv[0]):
            return None, (f"SQUAD_REVIEWER points to {argv[0]!r}, which is not installed or not on PATH. "
                          "Fix the command, or unset SQUAD_REVIEWER to use `codex exec`.")
        return argv, custom
    if not shutil.which("codex"):
        return None, ("no reviewer available: `codex` is not on PATH and SQUAD_REVIEWER is not set. "
                      "Install the Codex CLI, or set SQUAD_REVIEWER to a read-only command that takes "
                      "the prompt on stdin (e.g. `claude -p --model <model> --allowedTools Read,Grep,Glob`) "
                      "and run squad-review again. Do not advance the card without a verdict.")
    return ["codex", "exec", "--sandbox", "read-only", "--color", "never"], "codex exec --sandbox read-only"


def prompt(card_id, card, base, head, log, stat, diff):
    if len(diff) > MAX_DIFF:
        diff = diff[:MAX_DIFF] + (f"\n[... diff truncated at {MAX_DIFF} characters: read the rest with "
                                  f"`git diff {base}...{head}` in the working directory ...]\n")
    return f"""You are the heavy reviewer of an AgenFK card, and a different model from the one that wrote the code.
Work read-only: do not edit, create or delete files, do not commit, do not run anything that writes.
You may read the repository in the working directory and run read-only commands.

Review the change below against the card's acceptance criteria. Look for: criteria that are not met,
defects, failure modes and edge cases without a test, tests that cannot fail, masked failures
(skips, loosened asserts), security problems (secrets, injection, authorization), and anything
outside the card's scope. Tie every finding to a file and line, and say how severe it is.

SHIP only if every acceptance criterion is met and nothing blocks the merge. FIX_FIRST if the change
is right but has findings that must be fixed before the PR. REJECT if the approach is wrong.

The LAST line of your answer must be exactly one of:
VERDICT: SHIP
VERDICT: FIX_FIRST
VERDICT: REJECT

== Card {card_id} ==
{card}

== Commits {base}..{head} ==
{log.strip()}

== Files changed ==
{stat.strip()}

== Diff {base}...{head} ==
{diff}"""


def verdict(answer):
    """The verdict on the last non-empty line, or None. Nothing else counts."""
    lines = [ln for ln in answer.splitlines() if ln.strip()]
    if not lines:
        return None
    m = VERDICT_LINE.fullmatch(lines[-1])
    return m.group(1) if m else None


def ask(argv, text, cwd, timeout):
    """(rc, answer, error). For codex the answer is its last message, from -o."""
    out_file = None
    if argv[:2] == ["codex", "exec"]:
        fd, out_file = tempfile.mkstemp(prefix="squad-review-", suffix=".md")
        os.close(fd)
        argv = argv + ["--output-last-message", out_file, "-"]
    try:
        r = subprocess.run(argv, input=text, capture_output=True, text=True, cwd=cwd, timeout=timeout)
        answer = r.stdout
        if out_file:
            with open(out_file, encoding="utf-8") as fh:
                answer = fh.read() or r.stdout
        return r.returncode, answer, r.stderr
    except subprocess.TimeoutExpired:
        return None, "", f"the reviewer did not answer within {timeout} s"
    except OSError as e:
        return None, "", str(e)
    finally:
        if out_file and os.path.exists(out_file):
            os.unlink(out_file)


def main(args):
    rc, top = git("rev-parse", "--show-toplevel")
    rc2, gitdir = git("rev-parse", "--absolute-git-dir")
    if rc or rc2:
        return fail("this is not a git repository. Run squad-review inside the card's worktree.")
    top, gitdir = top.strip(), gitdir.strip()
    if git("rev-parse", "--verify", "-q", args.base + "^{commit}", cwd=top)[0]:
        return fail(f"base {args.base!r} does not exist here. Run `git fetch origin`, "
                    "or pass the branch the card starts from with --base.")
    head = git("rev-parse", "HEAD", cwd=top)[1].strip()
    _, diff = git("diff", "--no-color", "--no-ext-diff", f"{args.base}...HEAD", cwd=top)
    if not diff.strip():
        return fail(f"nothing to review: HEAD ({head[:12]}) has no changes against {args.base}. "
                    "Commit the card's work on its branch, or check --base, and run squad-review again.")
    card = read_card(args.card)
    if card is None:
        return fail(f"could not read card {args.card} with `agenfk get {args.card} --json`. "
                    "Check the id and that the AgenFK server is up (`agenfk health`), then run again.")
    argv, label = reviewer()
    if argv is None:
        return fail(label)
    if git("status", "--porcelain", "--untracked-files=no", cwd=top)[1].strip():
        print("squad-review: uncommitted changes are not reviewed; the review covers HEAD "
              f"{head[:12]} only.", file=sys.stderr)
    _, log = git("log", "--oneline", "--no-decorate", f"{args.base}..HEAD", cwd=top)
    _, stat = git("diff", "--stat", "--no-color", f"{args.base}...HEAD", cwd=top)
    timeout = env_int("SQUAD_REVIEW_TIMEOUT", 1800)
    code, answer, err = ask(argv, prompt(args.card, card, args.base, head, log, stat, diff), top, timeout)
    found = verdict(answer) if code == 0 else None

    folder = os.path.join(gitdir, "squad-review")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{head}.md" if found else f"{head}.invalid.md")
    header = (f"# Heavy review of {head}\n\n- Card: {args.card}\n- Base: {args.base}\n"
              f"- Reviewer: {label}\n- Date: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}\n\n")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header + answer.rstrip() + "\n")

    if code != 0:
        detail = (err or "").strip().splitlines()[-5:]
        return fail(f"the reviewer failed ({'exit ' + str(code) if code is not None else 'no exit'}): "
                    + " | ".join(detail) + f"\nWhat it printed is in {path}. Fix the reviewer and run "
                    "squad-review again; there is no verdict until then.")
    if found is None:
        return fail(f"the reviewer's answer does not end with `VERDICT: SHIP|FIX_FIRST|REJECT`, so there "
                    f"is no verdict. The answer is in {path}. Run squad-review again; do not read it as SHIP.")
    print(answer.rstrip())
    print(f"\nReport: {path}")
    if found != "SHIP":
        print("Back to IMPLEMENT: fix the findings, commit, and run squad-review on the new HEAD.")
    print(f"VERDICT: {found}")
    return 0 if found == "SHIP" else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser(prog="squad-review", description=__doc__.split("\n\n")[0])
    p.add_argument("--card", required=True, help="AgenFK card id")
    p.add_argument("--base", default="origin/main", help="ref the card branches from (default origin/main)")
    sys.exit(main(p.parse_args()))
