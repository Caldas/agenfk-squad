#!/usr/bin/env python3
"""PreToolUse hook of the pull-request skill: deny a PR whose title or body breaks the format.

Looks at the call Claude Code is about to make:
- Bash with `gh pr create|new|edit` or `agenfk pr create` in command position
  (text that only quotes the command, in a grep, a commit message or a
  heredoc, does not count);
- the MCP tool `mcp__plugin_github_github__create_pull_request`.
Runs `pr_check.py` on the title and the body, in the repository's language.
Failed: denies with the codes. Passed: lets the normal permission flow carry on.

Steps aside (exits 0, silent) when the repository has its own PR gate (a
skill in `.claude/skills/` with `pr` or `pull-request` in its name, or a
project hook / settings file that mentions `gh pr create`) or when
`SQUAD_PR_GATE=0`. An internal error never breaks the call: a warning on
stderr and the call goes ahead.

Registering it in settings.json is the owner's decision; see section 9 of
SKILL.md. Standard library only. Run it with `python3 -I`.
"""
import json
import os
import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.dont_write_bytecode = True  # the skill lives in a versioned repo: no __pycache__
SKILL = Path(os.path.realpath(__file__)).parent.parent
sys.path.insert(0, str(SKILL / "scripts"))
import pr_check  # noqa: E402

MCP_CREATE = "mcp__plugin_github_github__create_pull_request"
OWN_GATE_TEXT = "gh pr create"
OWN_GATE_MAX_FILES = 200
OWN_GATE_MAX_BYTES = 512_000
OPERATORS = ";&|()<>\n"
VALUE_FLAGS = {"--title": "title", "-t": "title", "--body": "body", "-b": "body",
               "--body-file": "body_file", "-F": "body_file", "--base": "base", "-B": "base"}
FILL_FLAGS = {"--fill", "-f", "--fill-first", "--fill-verbose"}
INTERACTIVE_FLAGS = {"--web", "-w", "--editor", "-e"}
HELP_FLAGS = {"--help", "-h"}
REPO_FLAGS = {"-R", "--repo"}
GH_ACTIONS = {"create", "new", "edit"}
# `{` too: a brace group runs in the current shell, so a `cd` inside it persists.
WRAPPERS = {"command", "exec", "nohup", "builtin", "stdbuf", "{"}
# Wrappers whose options take a value, so the value is not read as the program.
OPTION_VALUES = {
    "env": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"},
    "sudo": {"-u", "-g", "-h", "-p", "-C", "-U", "-r", "-t", "-D"},
    "timeout": {"-s", "--signal", "-k", "--kill-after"},
    "xargs": {"-I", "-n", "-L", "-P", "-d", "-E", "-s", "-a", "--max-args", "--max-procs",
              "--delimiter", "--arg-file", "--replace", "--max-lines", "--eof"},
    "nice": {"-n", "--adjustment"},
    "time": {"-f", "--format", "-o", "--output"},
}
SHELLS = {"bash", "sh", "zsh", "dash"}
HEREDOC = re.compile(r"<<(-?)\s*\\?(['\"]?)([A-Za-z_]\w*)\2")
# Cheap pre-filter: most Bash calls never mention a PR and skip parsing entirely.
MENTIONS_TOOL = re.compile(r"\b(gh|agenfk)\b")
MENTIONS_PR = re.compile(r"\bpr\b")
HEREDOC_SLOT = "__PR_GATE_HEREDOC_{}__"
SLOT = re.compile(r"__PR_GATE_HEREDOC_(\d+)__")
CAT_BODY = re.compile(r"\$\(\s*cat\s+(?:__PR_GATE_HEREDOC_(\d+)__|['\"]?([^\s)'\"]+)['\"]?)\s*\)")
ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*=")
# Last resort when a line cannot be tokenised: does it still look like opening a PR?
RAW_PR = re.compile(r"(^|[;&|(`]\s*|\bc\s+['\"]?)(\S*/)?(gh\s+pr\s+(\S+\s+)*?(create|new|edit)|agenfk\s+pr\s+create)\b")
MAX_BODY_BYTES = 1_000_000


@dataclass
class PrCommand:
    tool: str
    action: str
    cwd: str | None
    title: str | None = None
    body: str | None = None
    body_file: str | None = None
    base: str | None = None
    fill: bool = False
    interactive: bool = False
    unparseable: bool = False
    heredocs: list = field(default_factory=list)


def _scan(command, bodies):
    """Prepare the command for shlex the way bash reads it.

    Follows quotes and `$(...)` so only real syntax counts: joins `\\`
    continuations, drops a `#` comment that starts a word and cuts out the body
    of each heredoc, leaving a marker whose text goes in `bodies`. The body is
    never read as a command, and `--body "$(cat <<'EOF' ... EOF)"` still
    resolves to it. `<<` inside quotes, or without a terminator, opens nothing.
    """
    lines = command.split("\n")
    out, stack, i = [], [], 0
    while i < len(lines):
        line, new, pending, j = lines[i], [], [], 0
        while j < len(line):
            ctx = stack[-1] if stack else "top"
            c = line[j]
            if c == "\\" and j == len(line) - 1 and ctx != "sq" and i + 1 < len(lines):
                line = line[:j] + lines.pop(i + 1)
                continue
            if ctx == "sq":
                if c == "'":
                    stack.pop()
            elif ctx == "dq":
                if c == "\\":
                    new.append(line[j:j + 2])
                    j += 2
                    continue
                if c == '"':
                    stack.pop()
                elif line.startswith("$(", j):
                    stack.append("cmd")
                    new.append("$(")
                    j += 2
                    continue
            else:
                if c == "\\":
                    new.append(line[j:j + 2])
                    j += 2
                    continue
                if c == "#" and (j == 0 or line[j - 1] in " \t;&|()"):
                    break
                if c == "'":
                    stack.append("sq")
                elif c == '"':
                    stack.append("dq")
                elif line.startswith("$(", j) or (c == "(" and ctx == "cmd"):
                    stack.append("cmd")
                    new.append(line[j:j + 2] if c == "$" else c)
                    j += 2 if c == "$" else 1
                    continue
                elif c == ")" and ctx == "cmd":
                    stack.pop()
                elif line.startswith("<<<", j):
                    new.append("<<<")
                    j += 3
                    continue
                elif line.startswith("<<", j):
                    m = HEREDOC.match(line, j)
                    if m:
                        bodies.append("")
                        pending.append((m.group(1) == "-", m.group(3), len(bodies) - 1, m.group(0)))
                        new.append(HEREDOC_SLOT.format(len(bodies) - 1))
                        j = m.end()
                        continue
            new.append(c)
            j += 1
        text = "".join(new)
        i += 1
        for strip_tabs, term, idx, original in pending:
            k, body = i, []
            while k < len(lines):
                candidate = lines[k].lstrip("\t") if strip_tabs else lines[k]
                if candidate == term:
                    break
                body.append(candidate)
                k += 1
            if k == len(lines):
                text = text.replace(HEREDOC_SLOT.format(idx), original)
                continue
            bodies[idx] = "\n".join(body)
            i = k + 1
        out.append(text)
    return "\n".join(out)


def _tokens(command):
    lexer = shlex.shlex(command, posix=True, punctuation_chars=OPERATORS)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""  # _scan already dropped real comments; `fix#12` stays one word
    return list(lexer)


def _items(command):
    """("op", token), ("seg", tokens) or ("raw", line) for a scanned command."""
    try:
        chunks = [_tokens(command)]
    except ValueError:
        chunks = []
        for line in command.split("\n"):
            try:
                chunks.append(_tokens(line))
            except ValueError:
                chunks.append(None)
                yield "raw", line
    for tokens in chunks:
        if tokens is None:
            continue
        current = []
        for tok in tokens:
            if tok and all(c in OPERATORS for c in tok):
                if current:
                    yield "seg", current
                current = []
                yield "op", tok
            else:
                current.append(tok)
        if current:
            yield "seg", current


def _unwrap(seg):
    """Drop env assignments and wrappers (`env`, `sudo`, `timeout`, `xargs` ...) before the program."""
    while seg:
        head = os.path.basename(seg[0])
        if ASSIGNMENT.match(seg[0]) or head in WRAPPERS:
            seg = seg[1:]
        elif head in OPTION_VALUES:
            takes_value = OPTION_VALUES[head]
            seg = seg[1:]
            while seg and (seg[0].startswith("-") or (head in ("env", "sudo") and ASSIGNMENT.match(seg[0]))):
                seg = seg[2:] if seg[0] in takes_value else seg[1:]
            if head == "timeout" and seg:
                seg = seg[1:]  # the duration
        else:
            return seg
    return seg


def _parse_pr(seg, cwd):
    tool = os.path.basename(seg[0])
    if tool not in ("gh", "agenfk"):
        return None

    def skip_repo(xs):
        # gh accepts -R/--repo before and after `pr`: `gh -R o/r pr create`
        while tool == "gh" and xs and (xs[0] in REPO_FLAGS or xs[0].startswith("--repo=")):
            xs = xs[2:] if xs[0] in REPO_FLAGS else xs[1:]
        return xs

    head = skip_repo(seg[1:])
    if len(head) < 2 or head[0] != "pr":
        return None
    rest = skip_repo(head[1:])
    if not rest:
        return None
    action, args = rest[0], rest[1:]
    if not ((tool == "gh" and action in GH_ACTIONS) or (tool == "agenfk" and action == "create")):
        return None
    if any(a in HELP_FLAGS for a in args):
        return None
    pr = PrCommand(tool=tool, action="create" if action == "new" else action, cwd=cwd)
    i = 0
    while i < len(args):
        arg = args[i]
        flag, eq, value = arg.partition("=")
        if arg in FILL_FLAGS:
            pr.fill = True
        elif arg in INTERACTIVE_FLAGS:
            pr.interactive = True
        elif eq and flag in VALUE_FLAGS:
            setattr(pr, VALUE_FLAGS[flag], value)
        elif arg in VALUE_FLAGS and i + 1 < len(args):
            setattr(pr, VALUE_FLAGS[arg], args[i + 1])
            i += 1
        i += 1
    return pr


def find_pr_commands(command, cwd=".", bodies=None):
    bodies = [] if bodies is None else bodies
    text = _scan(command, bodies)
    found, dirs = [], []
    for kind, item in _items(text):
        if kind == "op":
            for ch in item:  # shlex joins neighbours: `)&&`, `);`
                if ch == "(":
                    dirs.append(cwd)
                elif ch == ")" and dirs:
                    cwd = dirs.pop()  # a subshell's cd does not outlive it
            continue
        if kind == "raw":
            if RAW_PR.search(item):
                found.append(PrCommand(tool="gh", action="create", cwd=cwd, unparseable=True))
            continue
        seg = _unwrap(item)
        if not seg:
            continue
        head = os.path.basename(seg[0])
        if head in ("cd", "pushd"):
            target = seg[1] if len(seg) > 1 else "~"
            if "$" in target or "`" in target:
                cwd = None  # computed at run time: unknown here
            elif target != "-":
                target = os.path.expanduser(target)
                cwd = target if os.path.isabs(target) else (str(Path(cwd, target)) if cwd else None)
            continue
        if head == "eval":
            found += find_pr_commands(" ".join(seg[1:]), cwd, bodies)
            continue
        if head in SHELLS:
            script = next((seg[i + 1] for i, a in enumerate(seg[:-1])
                           if a.startswith("-") and not a.startswith("--") and "c" in a), None)
            if script is not None:
                found += find_pr_commands(script, cwd, bodies)
            else:  # `bash <<EOF`: the heredoc is the script
                for tok in seg[1:]:
                    m = SLOT.fullmatch(tok)
                    if m:
                        found += find_pr_commands(bodies[int(m[1])], cwd, bodies)
            continue
        pr = _parse_pr(seg, cwd)
        if pr:
            pr.heredocs = bodies
            found.append(pr)
    return found


def _resolve_body(pr):
    """(text, error). Text None with no error: the command sets no body."""
    path = pr.body_file
    if path is None and pr.body is not None:
        m = CAT_BODY.fullmatch(pr.body.strip())
        if m and m[1] is not None:
            return pr.heredocs[int(m[1])], None
        if m:
            path = m[2]
        elif "$(" in pr.body or "`" in pr.body:
            return None, "the body comes from a command the gate does not run. Write it to a file and pass --body-file."
        else:
            return pr.body, None
    if path is None:
        return None, None
    if path == "-":
        return None, "a body read from stdin cannot be checked. Write it to a file and pass --body-file."
    path = os.path.expanduser(path)
    if not os.path.isabs(path) and pr.cwd is None:
        return None, (f"the command changes to a directory computed at run time, so {path} "
                      "cannot be found. Pass --body-file with an absolute path.")
    full = Path(pr.cwd or ".", path)
    if not full.is_file():
        return None, (f"the body file {path} does not exist yet. If this same command writes it, "
                      "write it in one call, run pr_check.py, and open the PR in a second call.")
    if full.stat().st_size > MAX_BODY_BYTES:
        return None, f"the body file {path} is over {MAX_BODY_BYTES // 1000} kB; a PR body is a page, not a log."
    try:
        return full.read_bytes().decode("utf-8"), None
    except UnicodeDecodeError:
        return None, f"the body file {path} is not UTF-8 text. Save it as UTF-8 and run again."


def _pr_named(name):
    """A skill name that is about PRs: the token `pr` or `pull-request` (acme-pr-delivery yes, prs-stack no)."""
    low = name.lower()
    return "pr" in re.split(r"[-_.\s]+", low) or re.search(r"pull[-_]?requests?", low) is not None


def own_pr_gate(path):
    """What in path's repository already plays this gate's role, or None.

    Only looks at the root of a git repository, never the owner's ~/.claude:
    the squad skill installed there is not a "project" gate.
    """
    root = pr_check.repo_root(path) if path else None
    if not root:
        return None
    root = Path(root).resolve()
    if root == Path.home().resolve():
        return None
    claude = root / ".claude"
    try:
        for d in sorted((claude / "skills").iterdir()):
            if d.is_dir() and _pr_named(d.name):
                return f".claude/skills/{d.name}"
    except OSError:
        pass
    candidates = [claude / "settings.json", claude / "settings.local.json"]
    try:
        candidates += sorted(p for p in (claude / "hooks").rglob("*") if p.is_file())[:OWN_GATE_MAX_FILES]
    except OSError:
        pass
    for p in candidates:
        try:
            if not p.is_file() or p.stat().st_size > OWN_GATE_MAX_BYTES:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if p.suffix == ".json" and p.parent == claude:
            # In a settings file only hooks count: `Bash(gh pr create:*)` in permissions
            # allows the command, it does not check the body.
            try:
                text = json.dumps(json.loads(text).get("hooks") or {})
            except (ValueError, AttributeError):
                continue
        if OWN_GATE_TEXT in text:
            return str(p.relative_to(root))
    return None


def _problems(pr, lang):
    """(problems, body, error) of a PR command."""
    if pr.unparseable:
        return [], None, ("the command could not be parsed (unbalanced quotes?), so the body "
                          "cannot be checked. Write the body to a file and pass --body-file.")
    if pr.interactive:
        return [], None, "a body written in the browser or the editor cannot be checked. Write it to a file and pass --body-file."
    body, error = _resolve_body(pr)
    if error:
        return [], None, error
    if pr.action == "create" and body is None:
        return [], None, ("no body. Write it from the pull-request skill template, "
                          "run pr_check.py and pass --body-file.")
    if pr.action == "create" and pr.title is None:
        return [], None, ("no --title. Without it the title comes from where the gate does not read "
                          "(the commits, or the AgenFK card title); pass it explicitly.")
    problems = pr_check.check_title(pr.title, lang) if pr.title is not None else []
    if body is not None:
        files = pr_check.changed_files(pr.cwd, pr.base) if pr.cwd else []
        problems += pr_check.check_body(body, pr_check.detect_kind(body, files), lang)
        problems += pr_check.repository_template_problems(body, pr.cwd)
    return problems, body, None


def _verdict(denials, langs):
    if denials:
        return "deny", ("PR format gate (pull-request skill). Fix and run again "
                        "(title: ~/.claude/skills/pull-request/SKILL.md; body: "
                        "templates/body.md):\n\n" + "\n\n".join(denials))
    head = "PR format gate passed (language " + ", ".join(sorted(langs)) + ")."
    return "allow", head


class _Langs:
    """Language per repository root, computed once per call."""

    def __init__(self):
        self.cache = {}

    def __call__(self, path):
        key = pr_check.repo_root(path) if path else None
        if key not in self.cache:
            self.cache[key] = pr_check.detect_lang(key)[0] if key else "en"
        return self.cache[key]


def evaluate(command, cwd):
    """(decision, message) for a Bash command; decision None when it neither opens nor edits a PR."""
    if not (MENTIONS_TOOL.search(command) and MENTIONS_PR.search(command)):
        return None, ""
    denials, langs, checked = [], set(), False
    lang_of = _Langs()
    for pr in find_pr_commands(command, cwd):
        if pr.action == "edit" and pr.title is None and pr.body is None and pr.body_file is None \
                and not pr.interactive:
            continue  # label, reviewer, base: nothing the format covers
        if own_pr_gate(pr.cwd or cwd):
            continue
        checked = True
        lang = lang_of(pr.cwd or cwd)
        langs.add(lang)
        label = f"{pr.tool} pr {pr.action}"
        problems, body, error = _problems(pr, lang)
        if error:
            denials.append(f"{label}: {error}")
        elif problems:
            denials.append(f"{label}:\n" + "\n".join(f"  {p}" for p in problems))
    if not checked:
        return None, ""
    return _verdict(denials, langs)


def evaluate_mcp(tool_input, cwd):
    """(decision, message) for the MCP create-PR tool."""
    if own_pr_gate(cwd):
        return None, ""
    lang = _Langs()(cwd)
    title, body = tool_input.get("title"), tool_input.get("body")
    label = "create_pull_request (MCP)"
    if not isinstance(title, str) or not title.strip():
        return _verdict([f"{label}: no title."], {lang})
    if not isinstance(body, str) or not body.strip():
        return _verdict([f"{label}: no body. Write it from the pull-request skill template."], {lang})
    problems = (pr_check.check_title(title, lang)
                + pr_check.check_body(body, pr_check.detect_kind(body, []), lang)
                + pr_check.repository_template_problems(body, cwd))
    if problems:
        return _verdict([f"{label}:\n" + "\n".join(f"  {p}" for p in problems)], {lang})
    return _verdict([], {lang})


def decide(payload):
    tool = payload.get("tool_name", "Bash")
    cwd = payload.get("cwd") or os.getcwd()
    tool_input = payload.get("tool_input") or {}
    if tool == MCP_CREATE:
        return evaluate_mcp(tool_input, cwd)
    if tool != "Bash":
        return None, ""
    return evaluate(tool_input.get("command") or "", cwd)


def main():
    if os.environ.get("SQUAD_PR_GATE") == "0":
        return 0
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
        decision, message = decide(payload)
    except Exception as e:  # a broken gate must not block every call: warn and step aside
        print(f"pr_gate: internal error, PR not checked ({type(e).__name__}: {str(e)[:300]}). "
              "Run pr_check.py by hand.", file=sys.stderr)
        return 0
    if decision is None:
        return 0
    out = {"hookEventName": "PreToolUse"}
    if decision == "deny":
        out.update(permissionDecision="deny", permissionDecisionReason=message)
    else:
        out["additionalContext"] = message
    print(json.dumps({"hookSpecificOutput": out}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
