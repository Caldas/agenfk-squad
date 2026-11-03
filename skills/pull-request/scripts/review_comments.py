#!/usr/bin/env python3
"""Turn review findings into a GitHub review with inline comments.

    review_comments.py --diff PR.diff --findings FINDINGS.json [--self-review] [--lang en|pt]
                       [--event APPROVE|REQUEST_CHANGES|COMMENT] [--verdict TEXT] [--commit SHA]

Prints the JSON for `gh api repos/{owner}/{repo}/pulls/<n>/reviews --input -`.
It only builds the payload: posting belongs to the owner, who confirms first
(squad rule 5), on the owner's own PR too.

Each finding is {"severity": "Blocking"|"Minor" (or "Bloqueante"|"Menor"), "path",
"line", optional "start_line", optional "side": "RIGHT"|"LEFT", "problem", "fix",
optional "suggestion"}. A finding whose lines fall in a diff hunk becomes an
inline comment with the problem and the requested fix; GitHub refuses comments
outside the diff, so the rest go in the review body.

With --self-review the event is always COMMENT: GitHub does not let the author
approve or request changes on their own PR.

Standard library only. Run it with `python3 -I`.
"""
import argparse
import json
import re
import sys
from pathlib import Path

# A colleague's PR is approved unless something is Blocking. Minor is a comment
# on the approving review, not a veto. For the verifier: Blocking = FIX_FIRST/REJECT.
SEVERITY_ALIASES = {"blocking": "Blocking", "bloqueante": "Blocking", "minor": "Minor", "menor": "Minor"}
SEVERITIES = ("Blocking", "Minor")
TEXT = {
    "pt": {"Blocking": "Bloqueante", "Minor": "Menor", "fix": "Correção",
           "Request changes": "Pedir mudanças", "Approve": "Aprovar", "Comment": "Comentar",
           "verdict": "Veredito", "fix_blocking": "Corrija os achados Bloqueantes antes do merge.",
           "minor_ok": "Os comentários Menores não bloqueiam o merge; trate aqui ou num PR seguinte.",
           "self": "Autorrevisão. O GitHub não deixa o autor aprovar nem pedir mudanças no próprio "
                   "PR, então cada achado é um comentário na linha dizendo o que corrigir.",
           "inline": "{n} comentário(s) no diff.", "outside": "Fora do diff",
           "head": "| Severidade | Onde | Problema | Correção |"},
    "en": {"Blocking": "Blocking", "Minor": "Minor", "fix": "Fix",
           "Request changes": "Request changes", "Approve": "Approve", "Comment": "Comment",
           "verdict": "Verdict", "fix_blocking": "Fix the Blocking findings before the merge.",
           "minor_ok": "The Minor comments do not block the merge; address them here or in a follow-up.",
           "self": "This is a self-review. GitHub does not let the author approve or request changes "
                   "on their own pull request, so each finding is an inline comment saying what to fix.",
           "inline": "{n} inline comment(s) on the diff.", "outside": "Outside the diff",
           "head": "| Severity | Where | Problem | Fix |"},
}
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
OCTAL = re.compile(rb"\\([0-7]{3})")


def _path(raw, prefix):
    """A diff header path, with git's C-style quoting undone (`"a/caf\\303\\251.md"`)."""
    raw = raw.split("\t")[0].strip()
    if raw.startswith('"') and raw.endswith('"'):
        data = raw[1:-1].encode("latin-1", "backslashreplace")
        data = OCTAL.sub(lambda m: bytes([int(m[1], 8)]), data)
        raw = data.decode("unicode_escape").encode("latin-1").decode("utf-8", "replace")
    return raw.removeprefix(prefix)


def diff_hunks(diff):
    """{path: [{"RIGHT": set(lines), "LEFT": set(lines)}, ...]} from a unified diff.

    Hunk lengths come from the `@@` header, so a content line that starts with
    `--- ` or `+++ ` (an SQL comment, `++ i;`) is never read as a file header.
    """
    files, path, hunk, old_path = {}, None, None, None
    left = right = old_left = new_left = 0
    for line in diff.splitlines():
        if hunk is not None and (old_left > 0 or new_left > 0):
            if line.startswith("\\"):
                continue
            if line.startswith("+"):
                hunk["RIGHT"].add(right)
                right, new_left = right + 1, new_left - 1
            elif line.startswith("-"):
                hunk["LEFT"].add(left)
                left, old_left = left + 1, old_left - 1
            else:  # context: commentable on either side
                hunk["RIGHT"].add(right)
                hunk["LEFT"].add(left)
                left, right = left + 1, right + 1
                old_left, new_left = old_left - 1, new_left - 1
            continue
        if line.startswith("diff --git"):
            path = hunk = None
        elif line.startswith("--- "):
            old_path = _path(line[4:], "a/")
        elif line.startswith("+++ "):
            new = line[4:].strip()
            path = old_path if new == "/dev/null" else _path(new, "b/")
        elif (m := HUNK.match(line)) and path:
            left, right = int(m[1]), int(m[3])
            old_left = int(m[2]) if m[2] is not None else 1
            new_left = int(m[4]) if m[4] is not None else 1
            hunk = {"RIGHT": set(), "LEFT": set()}
            files.setdefault(path, []).append(hunk)
    return files


def _validate(f):
    if not isinstance(f, dict):
        raise ValueError(f"each finding is a JSON object: {f!r}")
    if isinstance(f.get("line"), str):
        if not f["line"].strip().isdigit():
            raise ValueError(f"line must be a number: {f!r}")
        f["line"] = int(f["line"])
    if isinstance(f.get("start_line"), str) and f["start_line"].strip().isdigit():
        f["start_line"] = int(f["start_line"])
    f["severity"] = SEVERITY_ALIASES.get(str(f.get("severity") or "").strip().lower(), f.get("severity"))
    if f.get("severity") not in SEVERITIES:
        raise ValueError(f"severity must be Bloqueante/Blocking or Menor/Minor: {f!r}")
    for key in ("path", "problem", "fix"):
        if not str(f.get(key) or "").strip():
            raise ValueError(f"every finding needs a {key}: {f!r}")


def _place(f, hunks):
    """The inline-comment fields for a finding, or None when it is outside the diff."""
    line = f.get("line")
    if not isinstance(line, int):
        return None
    side = f.get("side", "RIGHT")
    start = f.get("start_line")
    if isinstance(start, int) and start > line:
        start, line = line, start  # GitHub needs start_line before line
    for hunk in hunks.get(f["path"], []):
        lines = hunk.get(side, set())
        if line in lines and (start is None or start in lines):
            placed = {"path": f["path"], "line": line, "side": side}
            if start is not None and start != line:
                placed.update(start_line=start, start_side=side)
            return placed
    return None


def _where(f):
    if isinstance(f.get("line"), int):
        start = f.get("start_line")
        return f"{f['path']}:{start}-{f['line']}" if start else f"{f['path']}:{f['line']}"
    return f["path"]


def _fenced(code, info=""):
    """A code block whose fence is longer than any backtick run inside the code."""
    longest = max((len(r) for r in re.findall(r"`+", code)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{info}\n{code.rstrip()}\n{fence}"


def _cell(text):
    return text.strip().replace("|", "\\|").replace("\r", "").replace("\n", "<br>")


def comment_body(f, inline=True, lang="en"):
    t = TEXT[lang]
    text = f"**{t[f['severity']]}.** {f['problem'].strip()}\n\n{t['fix']}: {f['fix'].strip()}"
    if f.get("suggestion"):
        # GitHub applies suggestions to lines of the new file only.
        applicable = inline and f.get("side", "RIGHT") == "RIGHT"
        text += "\n\n" + _fenced(f["suggestion"], "suggestion" if applicable else "")
    return text


def build_review(diff, findings, self_review=False, event=None, verdict=None, commit=None, lang="en"):
    t = TEXT[lang]
    if not isinstance(findings, list):
        raise ValueError("findings must be a JSON list")
    for f in findings:
        _validate(f)
    hunks = diff_hunks(diff)
    comments, outside = [], []
    for f in findings:
        placed = _place(f, hunks)
        if placed:
            comments.append({**placed, "body": comment_body(f, lang=lang)})
        else:
            outside.append(f)

    blocking = any(f["severity"] == "Blocking" for f in findings)
    label = "Request changes" if blocking else "Approve"
    if self_review:
        event = "COMMENT"
    elif event is None:
        event = "REQUEST_CHANGES" if blocking else "APPROVE"
    if event == "COMMENT" and not self_review:
        label = "Comment"

    parts = [f"**{t['verdict']}: {t[label]}.**" + (f" {verdict.strip()}" if verdict else "")]
    if blocking:
        parts.append(t["fix_blocking"])
    elif findings and not self_review:
        parts.append(t["minor_ok"])
    if self_review:
        parts.append(t["self"])
    if comments:
        parts.append(t["inline"].format(n=len(comments)))
    if outside:
        rows = [f"## {t['outside']}", "", t["head"], "|---|---|---|---|"]
        for f in outside:
            rows.append(f"| {t[f['severity']]} | `{_where(f)}` | {_cell(f['problem'])} | {_cell(f['fix'])} |")
        parts.append("\n".join(rows))
        for f in outside:
            if f.get("suggestion"):
                parts.append(f"`{_where(f)}`:\n\n" + _fenced(f["suggestion"]))

    review = {"event": event, "body": "\n\n".join(parts), "comments": comments}
    if commit:
        review["commit_id"] = commit
    return review


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build a GitHub review with inline comments from findings.")
    ap.add_argument("--diff", required=True, help="the PR diff (gh pr diff <n>)")
    ap.add_argument("--findings", required=True, help="findings JSON file, or - for stdin")
    ap.add_argument("--self-review", action="store_true", help="the reviewer is the PR author")
    ap.add_argument("--event", choices=("APPROVE", "REQUEST_CHANGES", "COMMENT"))
    ap.add_argument("--verdict", help="one sentence after the verdict label")
    ap.add_argument("--commit", help="PR head SHA the comments refer to")
    ap.add_argument("--lang", choices=("en", "pt"), default="en", help="language of the review text")
    args = ap.parse_args(argv)
    raw = sys.stdin.read() if args.findings == "-" else Path(args.findings).read_text()
    try:
        review = build_review(Path(args.diff).read_text(), json.loads(raw), args.self_review,
                              args.event, args.verdict, args.commit, args.lang)
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        print(f"invalid findings: {e}", file=sys.stderr)
        return 2
    print(json.dumps(review, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
