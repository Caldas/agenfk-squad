#!/usr/bin/env python3
"""Squad sentinel: watches every Claude Code session and sub-session from the inside.

Registered on PreToolUse, PostToolUse, SubagentStop and UserPromptSubmit
(PostToolUseFailure, where the harness has it, only gives a merge turn back).

  PostToolUse       records the call; warns about loops; every CHECK_EVERY seconds
                    reads what was appended to the transcript and redoes the math
                    (session_context.handoff_math): context, burn, reread versus
                    new work, payback. A sub-session at the threshold is ordered
                    to send back the return handoff; a main session is ordered to
                    write the handoff (clear-pickup mode A) on its own, before it
                    overflows.
  PreToolUse        sub-sessions only: denies the identical repeated call (loop)
                    and, above the context ceiling, denies everything except
                    git/agenfk, so the sub-session has to send back the return
                    handoff.
  SubagentStop      writes the sub-session's metrics to ~/.claude/squad/metrics.jsonl
                    and leaves a note for the parent session when it ended badly.
  UserPromptSubmit  delivers the pending notes to the main session.
  Stop              main session at handoff level: if it stopped without writing
                    the handoff, the order is sent back; if it stops again
                    without it, the watcher writes the handoff itself (git, the
                    owner's last request, denied dispatches). With a handoff and
                    nothing running in the background, it launches
                    squad-switch.py, which clears the herdr pane and calls the
                    pickup, so the session switch happens without the owner.
                    SQUAD_SWITCH=0 turns the switch off.

The stop is always soft: the watcher warns first (DISPATCH NOTICE), only the new
dispatch is denied, the task in progress finishes, and it is the watcher that
drives the handoff and the restart of the work in the new session. The brief of
every denied dispatch is kept in full in
~/.claude/squad/handoffs/<session>-dispatches.md.

It never brings a session down: any error ends silently with exit code 0. What
it prints is data measured here; tool and agent names go through clean() before
they leave.

Thresholds, by environment variable:
  SQUAD_SUB_CTX_WARN (120000)  SQUAD_SUB_CTX_CUT (180000)  context tokens
  SQUAD_SUB_BURN      (2000000) weighted burn of one sub-session
  SQUAD_WINDOW                  window of the main session (default: 1000000)
  SQUAD_CTX_BASE      (40000)   context of a fresh session, for the payback
  The main session's handoff (level 2) is arithmetic, with no judgement by the agent:
      context >= SQUAD_CTX_PCT (80)% of the window, OR
      reread >= SQUAD_REREAD (60)% AND context >= floor
      (reread = 0.1*cache-read / weighted burn, the cockpit's REREAD %; minimum floor 2*CTX_BASE)
  The floor weighs the burn: SQUAD_REREAD_FLOOR (50)% of the window once the burn
  has reached SQUAD_BURN_FULL (50)% of the session budget (CLAUDE_SESSION_BUDGET,
  20M, the cockpit's BURN %), rising in a straight line to 80% with zero burn.
  Context at 50% with burn at 10% is NOT handoff time: the floor there is 74%. A
  session that has just built its context and barely used it is not cut.
  In other words: the cut falls between 50% and 80% of the window. Above 50%
  without the math closing, only an informational notice goes out (level 1),
  with no order to stop.
  SQUAD_CTX_WARN (0) SQUAD_CTX_HANDOFF (0)  absolute thresholds in tokens, off by default
  SQUAD_CTX_CEILING (600000)    above this, dispatch denied and handoff ordered
  SQUAD_MAX_SUBS      (40)      sub-sessions per main session
  SQUAD_MAX_ORCH      (3)       sessions orchestrating sub-agents at the same time
  SQUAD_ORCH_HERE     (120000)  no orchestrator slot: below this the card is done
                                in the session itself; from here up, handoff with
                                the plan and a new session
  SQUAD_MAX_REVIEWS   (6)       reviewer dispatches for the same card
  SQUAD_WATCH=0                 turns it off

A denied dispatch is never just a "no": the message says where the work continues.
  context ceiling / sub-session ceiling  handoff with the plan of the denied dispatch;
                                     the session switch is armed and the pickup continues
  no orchestrator slot, implementation
      context <  SQUAD_ORCH_HERE     implement right here, with no agent
      context >= SQUAD_ORCH_HERE     handoff with the implementation plan; the new
                                     session (clean context) implements directly
  no orchestrator slot, reviewer     carry on with whatever does not depend on the
                                     verdict; the watcher announces SLOT FREE when
                                     there is a slot
  7th reviewer on the same card      the owner's decision, with what keeps failing

Merge turn (one per repository, ~/.claude/squad/turn/): the turn covers only the
merge call itself (`gh pr merge`, direct push to the trunk, merge_pull_request), not
the sync, the suite or CI. Holding it through all of that left sessions waiting
for hours.
  merge call
      turn free or yours     the PreToolUse takes it; the PostToolUse of the same
                             call gives it back, success or failure (also on
                             PostToolUseFailure); a turn held longer than
                             SQUAD_TURN_HOLD (120 s) expired
      another session's      denied for those seconds: repeat the merge shortly
  before a PR merge, with the turn held: `git fetch` of the base and
      `git merge-tree --write-tree origin/<base> <PR head>`. A conflict is
      denied (MERGE CONFLICT) with the files and where the work continues; a
      clean merge passes, with no new suite asked for.
  seal (opt-in: `git config squad.seal true`, or SQUAD_SEAL=1; SQUAD_SEAL=0 turns
      it off): a PR merge passes only if the PR head SHA has a SHIP seal, a push
      to the trunk only if the pushed SHA has one (MERGE SEAL). Seals are written
      by `squad-seal record` in ~/.claude/squad/seals/<repo hash>/<sha>.json.
  trunk: main, master, the remote's default branch (origin/HEAD, or `gh repo
      view` when that ref is missing) and `git config squad.trunk` (a
      comma-separated list); a push whose destination, or whose push target with
      no refspec, is one of them is a push to the trunk; so is `push origin HEAD`
      with the trunk checked out.
  where: a merge or push is checked in the directory it runs in, the cwd moved
      by each literal `cd` before it and by `git -C`. When that cannot be told
      (a variable or quotes in the path, `cd -`, a subshell, pushd, GIT_DIR,
      env -C, a missing directory) and the seal is on or unknown, it is denied.
  sync with main is never denied.
  `squad-turn request [PR] | release | status`   record an intent (it blocks
      nobody), drop it, see who is merging and the intents
SQUAD_TURN=0 turns all of it off: the turn, the conflict check and the seal.
With the seal on, a check that cannot run (git or gh failing or timing out, an
unreadable seal, an unknown PR head, an exception) denies the merge. Merge
commands are recognised in any position (bash -c, ssh, eval, xargs, watch...);
text counts as data only as the value of -m/-d/--body/--title/--description/
--evidence or an echo/printf argument on a line of inert commands. This guards
against an agent's mistake, not against someone set on getting around it: the
guarantee comes from the squad/seal commit status required by the branch
protection on the trunk.

The dispatch ceilings exist because of one week of October 2026: orchestrators
with 420-966k of context, 249 sub-agents (64% of the consumption), five projects
orchestrating overnight and one card judged five times.
"""
import fcntl
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
BASE = os.path.join(HOME, ".claude", "squad")
STATE = os.path.join(BASE, "watch")
LOG = os.path.join(BASE, "metrics.jsonl")
SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
                       "skills", "session-context", "scripts")

MUTATING = {"Edit", "Write", "NotebookEdit", "MultiEdit"}
WINDOW = 30            # most recent calls considered
WARN_AT = 3            # same call N times: warning
DENY_AT = 5            # sub-session: the Nth identical call is denied
STREAK_DENY = 3        # sub-session: N identical calls in a row, the next one is denied
CHECK_EVERY = 60       # seconds between measurements of the transcript
RETURN_HANDOFF = ("Send back the return handoff now, in at most 12 lines: DONE (commits and "
                  "files, with evidence), REMAINING, NEXT STEP, BLOCKER. If your role "
                  "writes code, first run `git add -u` (tracked files only; a new file stays out of the commit and goes under REMAINING, by name) and `git commit -m \"wip: ...\"` on the card's branch "
                  "(separate commands, no `-C`, message with letters, digits and simple punctuation only).")


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


CTX_WARN = env_int("SQUAD_SUB_CTX_WARN", 120_000)
CTX_CUT = env_int("SQUAD_SUB_CTX_CUT", 180_000)
BURN_WARN = env_int("SQUAD_SUB_BURN", 2_000_000)
MAIN_WARN = env_int("SQUAD_CTX_WARN", 0)         # 0 = no absolute threshold; only the % of the window applies
MAIN_HANDOFF = env_int("SQUAD_CTX_HANDOFF", 0)
MAIN_CEIL = env_int("SQUAD_CTX_CEILING", 600_000)
MAIN_PCT = min(max(env_int("SQUAD_CTX_PCT", 80), 10), 100)       # % of the window at which the handoff goes out regardless
MAX_SUBS = env_int("SQUAD_MAX_SUBS", 40)
MAX_ORCH = env_int("SQUAD_MAX_ORCH", 3)
MAX_REV = env_int("SQUAD_MAX_REVIEWS", 6)
ORCH_HERE = env_int("SQUAD_ORCH_HERE", 120_000)
DISPATCH = {"Agent", "Task"}
REVIEWER = re.compile(r"verif|review|revis|segur|secur|audit|advers", re.I)
CARD = re.compile(r"\b(?:[A-Z][A-Z0-9]{1,6}-\d+[a-z]?|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b")
ORCH_LIVE = 600        # seconds: a sub-session with activity within this interval counts as live


TURN = os.path.join(BASE, "turn")
SEALS = os.path.join(BASE, "seals")
TURN_HOLD = env_int("SQUAD_TURN_HOLD", 120)    # seconds: a turn held longer than this died with its merge call
INTENT_TTL = 3600      # seconds an intent from `squad-turn request` stays listed
AT = r"(?:^|[;&|(\n])\s*"                 # command position, for the squad-turn CLI only
# The merge patterns match ANYWHERE in the text (bash -c, ssh, eval, xargs, watch...):
# only spans proven to be data are blanked out first, see merge_text().
PR_MERGE = re.compile(r"\bgh(?:[ \t]+[^\s;&|]+)*?[ \t]+pr\s+merge\b((?:[ \t]+-[^\s;&|]+)*[ \t]+(?:#?(\d+)\b|\S*/pull/(\d+)))?")
API_MERGE = re.compile(r"/pulls/(\d+)/merge\b|\bmergePullRequest\b|(?:\bgh\s+api\b|api\.github\.com)[^;&|\n]*/merges\b")
GIT_PUSH = re.compile(r"\bgit((?:[ \t]+-[Cc][ \t]+\S+|[ \t]+--?[A-Za-z][\w-]*(?:=\S+)?)*)[ \t]+push\b([^;&|\n]*)")
# Where a merge or push runs: each `cd` before it moves the directory; these make it unknown.
CD = re.compile(r"(?:^|[;&|(\n{\"'])[ \t]*cd(?=[\s;&|)\"']|$)([^;&|\n)]*)")
ELSEWHERE = re.compile(r"\bGIT_(?:DIR|WORK_TREE)=|--git-dir\b|--work-tree\b|\benv\b[^;&|\n]*[ \t]-C\b|\b(?:pushd|popd)\b")
LITERAL_DIR = re.compile(r"[A-Za-z0-9._/~+,@%=-]+")
TURN_CLI = re.compile(AT + r"(?:\S*/)?squad-turn(?:\.py)?\s+(request|release|status)\b(?:\s+#?(\d+))?")
# What merge_text() may treat as data. Anything else on the line, or any doubt, counts as code.
OPAQUE = re.compile(r"\$[({'\[]|`|[<>]\(|<<")      # substitutions, ANSI-C quotes, heredocs
REDIR_OK = re.compile(r"(?:\d*|&)>(?:&\d|>?[ \t]*/dev/null)(?=[\s;&|]|$)")
DATA_OPTS = {"-m", "--message", "-d", "--description", "--body", "--title", "--evidence"}
INERT = {"cd", "echo", "printf", "git", "gh", "agenfk", "squad-seal", "squad-turn", "true", "pwd", "ls",
         "cat", "grep", "rg", "head", "tail", "wc", "sleep", "mkdir"}
GIT_SAFE = {"commit", "tag", "merge", "notes", "stash", "revert", "cherry-pick", "status", "log", "diff",
            "add", "show", "branch", "fetch", "push", "rev-parse", "switch", "checkout", "worktree", "pull"}
GH_SAFE = {"pr", "issue", "release", "repo", "api"}
BRANCH = re.compile(r"[A-Za-z0-9._/-]{1,200}")
SHA = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
# `gh pr merge` flags (gh 2.x `--help`): which take a value, which do not. Any other flag makes the target unknown.
MERGE_VALUED = {"-A", "--author-email", "-b", "--body", "-F", "--body-file", "--match-head-commit",
                "-t", "--subject", "-R", "--repo"}
MERGE_BOOL = {"--admin", "--auto", "-d", "--delete-branch", "--disable-auto", "-m", "--merge", "-r", "--rebase",
              "-s", "--squash", "--help"}
PR_URL = re.compile(r"https://[A-Za-z0-9.-]+/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/pull/\d+/?")
GH_REPO = re.compile(r"(?:[A-Za-z0-9.-]+/)?[A-Za-z0-9._-]+/[A-Za-z0-9._-]+")


def ctx_lib():
    sys.path.insert(0, SCRIPTS)
    import session_context  # noqa: E402  (same weights and same reading as the report)
    return session_context


def safe(s):
    return "".join(c for c in str(s or "") if c.isalnum() or c in "-_")[:80]


def state_path(session, agent):
    return os.path.join(STATE, f"{safe(session)}.{safe(agent) or 'main'}.json")


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
            return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save(path, st):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(st, fh)
    os.replace(tmp, path)


NOISE = {"description", "timeout", "run_in_background"}   # they change without changing the call


def call_hash(p):
    inp = p.get("tool_input")
    if isinstance(inp, dict):
        inp = {key: v for key, v in inp.items() if key not in NOISE}
    raw = json.dumps([p.get("tool_name"), inp], sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:12]


def streak(calls, h):
    n = 0
    for c in reversed(calls):
        if c != h:
            break
        n += 1
    return n


def sub_transcript(p):
    t = p.get("agent_transcript_path")
    if t:
        return t
    main, agent = p.get("transcript_path") or "", p.get("agent_id")
    if not (main.endswith(".jsonl") and agent):
        return ""
    return os.path.join(main[:-6], "subagents", f"agent-{safe(agent)}.jsonl")


def measure(path):
    """Current context, weighted burn and reread share of a transcript."""
    if not path or not os.path.isfile(path):
        return None
    cx = ctx_lib()
    st = cx.blank()
    cx.scan_claude(path, st)
    if not st["req"]:
        return None
    c = cx.handoff_math(st["inp"], st["wr"], st["rd"], st["out"], st["ctx"])
    return {"ctx": st["ctx"], "burn": c["burn"], "calls": sum(st["tools"].values()),
            "reread": c["share"], "ratio": c["ratio"],
            "started": st["started"], "last": st["last"], "cwd": st["cwd"], "model": st["model"]}


def fold(path, tok):
    """Adds to `tok` only what was appended to the transcript since the last
    read (whole lines), so it costs the same on a 5 MB session or a 50 MB one."""
    for key in ("offset", "inp", "wr", "rd", "out", "ctx", "req"):
        tok.setdefault(key, 0)
    tok.setdefault("last", "")
    try:
        size = os.path.getsize(path)
        if size < tok["offset"]:
            tok.update(offset=0, last="", inp=0, wr=0, rd=0, out=0, ctx=0, req=0)
        if size <= tok["offset"]:
            return tok
        with open(path, "rb") as fh:
            fh.seek(tok["offset"])
            blob = fh.read(size - tok["offset"])
    except OSError:
        return tok
    cut = blob.rfind(b"\n")
    if cut < 0:
        return tok
    tok["offset"] += cut + 1
    for raw in blob[:cut].split(b"\n"):
        if b'"usage"' not in raw:
            continue
        try:
            rec = json.loads(raw)
            u = (rec.get("message") or {}).get("usage") or {}
        except (ValueError, AttributeError):
            continue
        if rec.get("type") != "assistant" or not u:
            continue
        req = rec.get("requestId") or ""
        if req and req == tok["last"]:
            continue
        tok["last"] = req
        tok["req"] += 1
        tok["inp"] += u.get("input_tokens", 0)
        tok["wr"] += u.get("cache_creation_input_tokens", 0)
        tok["rd"] += u.get("cache_read_input_tokens", 0)
        tok["out"] += u.get("output_tokens", 0)
        tok["ctx"] = (u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                      + u.get("cache_read_input_tokens", 0))
    return tok


def main_window(session):
    """Window of the main session: SQUAD_WINDOW if set; otherwise 1M, or the one a status line
    recorded if larger."""
    w = env_int("SQUAD_WINDOW", 0)
    if w:
        return w
    store = load(os.path.join(HOME, ".claude", "cache", "session-tokens", f"{safe(session)}.json"))
    try:
        return max(int(store.get("window") or 0), 1_000_000)
    except (TypeError, ValueError):
        return 1_000_000


def figures(c, ctx):
    pay = f"a new session pays for itself in {c['payback']:g} turn(s)" if c["payback"] else "no gain from restarting"
    return (f"reread {c['share']:.0%}, each turn rereads {k(c['toll'])} weighted tokens, {pay}")


def cx_share():
    return ctx_lib().REREAD_SHARE


def k(n):
    return f"{n / 1000:.0f}k" if n < 1e6 else f"{n / 1e6:.1f}M"


def emit(event, text):
    if not text:
        return
    if event == "UserPromptSubmit":
        print(text)
    else:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}))


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": reason}}))


def pending(session, pop=True):
    path = state_path(session, "")
    st = load(path)
    notes = st.get("pending") or []
    if notes and pop:
        st["pending"] = []
        save(path, st)
    return notes


# After the cut: subcommand -> accepted flags. A positional argument (path,
# ref, message) passes; any other flag does not. Left out is everything that
# writes outside the index/commit or runs a program: --output, --ext-diff,
# --amend, --no-verify, -c, stash, show, push, branch -D...
GIT_CLOSING = {
    "status": {"-s", "--short", "--porcelain", "-b", "--branch"},
    "add": {"-u", "--update"},           # no -A: a new untracked file may be a secret
    "commit": {"-m", "--message", "-a", "--all", "-am"},
    "diff": {"--stat", "--cached", "--staged", "--name-only", "--name-status"},
    "log": {"--oneline", "--stat", "-n"},
    "rev-parse": {"--show-toplevel", "--abbrev-ref", "--short"},
    "branch": {"--show-current"},
}
# Only characters that bash and shlex read the same way: no expansion,
# comment, glob, escape, chaining or redirection.
PLAIN = re.compile(r"[A-Za-z0-9 _./:,=@+\-\"']*")


def closing_command(cmd, cwd=""):
    """After the cut only a simple closing command passes: `git <subcommand>`
    with the flags in the table, or `agenfk comment|get <id> ...`."""
    if not PLAIN.fullmatch(cmd):
        return False
    try:
        t = shlex.split(cmd)
    except ValueError:
        return False
    if len(t) >= 3 and t[0] == "agenfk" and t[1] in ("comment", "get"):
        return all(a == "--json" or not a.startswith("-") for a in t[2:])
    if not t or t[0] != "git":
        return False
    i = 1
    # No -C: being below the cwd does not prove it is the same repository
    # (another card's worktree, a submodule, a nested repo). git acts where the shell is.
    if i >= len(t) or t[i] not in GIT_CLOSING:
        return False
    sub, flags, args = t[i], GIT_CLOSING[t[i]], t[i + 1:]
    if sub == "branch":
        return args == ["--show-current"]
    j = 0
    while j < len(args):
        a = args[j]
        if a in ("-m", "--message", "-am") and sub == "commit":
            j += 2                       # the message is the next argument, any text
            continue
        if a == "-n" and sub == "log" and j + 1 < len(args) and args[j + 1].isdigit():
            j += 2
            continue
        if a.startswith("-") and a not in flags:
            return False
        if not a.startswith("-") and not (sub == "rev-parse" and a == "HEAD"):
            return False                 # no loose path or ref: `git add <file>` could carry
        j += 1                           # a secret, `git diff a b` reads a file outside the repo
    return True


def review_key(p):
    """(type, card) when the call dispatches a reviewer for a card."""
    inp = p.get("tool_input") or {}
    kind = str(inp.get("subagent_type") or "")
    if not REVIEWER.search(kind):
        return None
    m = CARD.search(str(inp.get("prompt") or "") + " " + str(inp.get("description") or ""))
    # no card id in the brief still counts, in a single bucket: leaving the id out does not reset the ceiling
    return f"{safe(kind)}:{m.group(0) if m else 'no-card'}"


def other_orchestrators(session):
    """Other main sessions with a live sub-session right now."""
    own, live, now = safe(session), set(), time.time()
    try:
        for name in os.listdir(STATE):
            sid, _, rest = name.partition(".")
            if not sid or sid == own or rest.startswith("main.") or not name.endswith(".json"):
                continue
            if now - os.path.getmtime(os.path.join(STATE, name)) < ORCH_LIVE:
                live.add(sid)
    except OSError:
        pass
    return len(live)


def keep_brief(session, p):
    """Keeps the brief of the denied dispatch in full: it is the plan the session
    already wrote, and it cannot depend on the session rewriting it from memory
    in the handoff."""
    inp = p.get("tool_input") or {}
    text = str(inp.get("prompt") or "").strip()
    if not text:
        return ""
    path = os.path.join(BASE, "handoffs", f"{safe(session)}-dispatches.md")
    mark = call_hash(p)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        old = ""
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                old = fh.read()
        if mark not in old and len(old) < 80_000:
            desc = " ".join(str(inp.get("description") or "").split())[:120]
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"\n## Dispatch denied at {time.strftime('%Y-%m-%d %H:%M:%S')} — agent "
                         f"`{safe(inp.get('subagent_type')) or '?'}` — {desc} <!-- {mark} -->\n\n{text[:20_000]}\n")
    except OSError:
        return ""
    return path


def plan(resume_how, brief=""):
    """What the handoff of a denied dispatch has to carry, and how it is resumed."""
    return ("Soft stop: only the new dispatch is denied; nothing else is blocked and the work continues "
            "in a new session, driven by the watcher. (1) Finish the task in progress (commit what is "
            "open) and, if a sub-session of yours is running, wait for it to return. (2) Comment on the card (`agenfk "
            "comment <id> \"PAUSE: done X, remaining Y\"`). (3) Write the handoff with mode A of the "
            "`clear-pickup` skill (Write tool, new file) with the PLAN of the denied dispatch under Next "
            "step, ready to run without this conversation: card, branch, worktree, files to touch, "
            "steps in order, acceptance criteria and the suite command. " + (
                f"The denied brief is already kept in full at {brief}: point to that file instead "
                "of rewriting it. " if brief else "") + resume_how +
            " (4) End your reply with the handoff path and stop. " + (
                "The watcher clears this session and calls the pickup on its own: the work continues in the new session."
                if can_switch() else
                "Tell the owner, with the path: `/clear` and `/clear-pickup pickup <file>` in this pane, or "
                "the same pickup in a new session opened in the card's worktree."))


def pre_dispatch(p):
    """The orchestrator's brake: when dispatching one more agent is the mistake.
    Every denial goes out with the path along which the work continues."""
    session = p.get("session_id")
    st = load(state_path(session, ""))
    ctx, why, handoff = st.get("ctx", 0), None, False
    brief = keep_brief(session, p)
    if ctx >= MAIN_CEIL:
        handoff = True
        why = (f"this session is orchestrating with {k(ctx)} of context (ceiling {k(MAIN_CEIL)}): every turn and "
               "every agent return rereads all of it. " + plan(
                   "The new session, with a clean context, dispatches that plan.", brief))
    elif st.get("subs", 0) >= MAX_SUBS:
        handoff = True
        why = (f"this session has already dispatched {st['subs']} sub-sessions (ceiling {MAX_SUBS}). " + plan(
            "The new session, with the count reset, dispatches that plan.", brief))
    elif other_orchestrators(session) >= MAX_ORCH:
        cap = f"there are already {MAX_ORCH} or more sessions orchestrating sub-agents right now"
        if review_key(p):
            st["wait_slot"] = True
            why = (f"{cap}, and a review is not something you do yourself (whoever writes does not approve). Carry on "
                   "with whatever does not depend on the verdict (tests, a card comment, another step of the request). The "
                   "watcher announces SLOT FREE in this session when there is a slot: dispatch the reviewer then. If "
                   "nothing is left but the review, stop and tell the owner that only the review remains, for lack of a slot")
        elif ctx < ORCH_HERE:
            st["wait_slot"] = True
            why = (f"{cap}. This session is light ({k(ctx)} of context): do this card RIGHT HERE, with no "
                   "agent and no handoff. One card, in its own worktree and branch, `agenfk gatekeeper "
                   "--item-id <id>` before editing, the project's suite as the gate. The review still "
                   "belongs to the `verifier`: the watcher announces SLOT FREE when there is a slot")
        else:
            handoff = True
            why = (f"{cap}, and this session is at {k(ctx)} of context: implementing here would reread all of it "
                   "on every turn. " + plan(
                       "Also write: \"implement directly in this session, without dispatching an agent\" (the "
                       "new session starts light and does the card itself).", brief))
    else:
        key = review_key(p)
        n = (st.get("rev") or {}).get(key, 0) if key else 0
        if n >= (MAX_REV * 3 if key and key.endswith(":no-card") else MAX_REV):
            why = (f"the reviewer has already been dispatched {n}x for this card ({key}). One more round is not "
                   "review, it is a loop. Comment on the card what keeps failing (`agenfk comment`), stop and "
                   "take the choice to the owner: fix it another way, split the card or accept the risk")
    if why:
        st["blocked"] = st.get("blocked", 0) + 1
        again = ""
        if handoff:                       # the watcher ordered a handoff: the switch on Stop is armed
            if st.get("ordered"):
                again = " This handoff has already been ordered: trying to dispatch again does not change the answer."
            st["ctx_level"] = 2
            st["ordered"] = True
            st.setdefault("alert_ts", time.time())
        save(state_path(session, ""), st)
        deny("[squad-watch] DISPATCH DENIED: " + why + "." + again)


def dispatch_notice(session, st, ctx):
    """Notice ahead of the brake, only for a session that orchestrates: whoever
    is going to have the next dispatch turned into a handoff finds out while the
    task is in progress, not in the middle of it. One notice per reason; the
    slot one re-arms when the slot comes back."""
    if not st.get("subs") or st.get("ctx_level", 0) >= 2:
        return []
    tail = ("Nothing changes now: finish the task in progress normally and leave what is open committed. "
            "A new implementation dispatch will be denied and turned into a handoff with the plan; the watcher "
            "switches the session and the work continues there.")
    out = []
    if ctx >= 0.9 * MAIN_CEIL and not st.get("ceil_warned"):
        st["ceil_warned"] = True
        out.append(f"[squad-watch] DISPATCH NOTICE — context {k(ctx)}, orchestrator ceiling "
                   f"{k(MAIN_CEIL)}. {tail}")
    full = ctx >= ORCH_HERE and other_orchestrators(session) >= MAX_ORCH
    if full and not st.get("orch_warned"):
        out.append(f"[squad-watch] DISPATCH NOTICE — all {MAX_ORCH} orchestrator slots are taken "
                   f"and this session is at {k(ctx)}. {tail} A reviewer waits for the SLOT FREE notice.")
    st["orch_warned"] = full
    return out


# --------------------------------------------------------------- merge queue
def git_dir(cwd):
    """Common git directory (the same for every worktree of the repository)."""
    try:
        r = subprocess.run(["git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                           capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL)
        return os.path.realpath(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def shell_split(cmd):
    """Simple commands of a line, each a list of words (start, end, text without
    quotes). None for anything this reader does not follow exactly as the shell
    does: a subshell, a redirection other than to /dev/null or another fd, an
    unterminated quote."""
    cmds, words, i, n = [], [], 0, len(cmd)
    while i < n:
        c = cmd[i]
        m = REDIR_OK.match(cmd, i)
        if m:
            i = m.end()
        elif c in " \t":
            i += 1
        elif c in ";&|\n":
            if words:
                cmds.append(words)
                words = []
            i += 1
        elif c in "()":
            return None
        elif c == "#":                                     # a comment runs to the end of the line
            j = cmd.find("\n", i)
            i = n if j < 0 else j
        else:
            start, text = i, []
            while i < n and cmd[i] not in " \t;&|\n()":
                c = cmd[i]
                if c == "\\":
                    text.append(cmd[i + 1:i + 2])
                    i += 2
                elif c in "'\"":
                    j = i + 1
                    while j < n and cmd[j] != c:
                        j += 2 if c == '"' and cmd[j] == "\\" else 1
                    if j >= n:
                        return None
                    text.append(cmd[i + 1:j])
                    i = j + 1
                elif c in "<>":
                    return None
                else:
                    text.append(c)
                    i += 1
            words.append((start, i, "".join(text)))
    if words:
        cmds.append(words)
    return cmds


def merge_text(cmd):
    """The text the merge patterns are matched against: the command without
    quotes and backslashes (so `gh pr "mer""ge"` still reads as a merge), with
    the spans that are provably data blanked out. Data is only the value of
    -m/--message/-d/--description/--body/--title/--evidence, or an argument of
    echo/printf, and only on a line where every command is one of INERT (git and
    gh with a safe subcommand). Any substitution, heredoc, subshell, redirection
    into a file, variable or unknown command makes the whole line count: in
    doubt, it is a merge."""
    def plain(s):
        return re.sub(r"[\\'\"]", "", s)
    cmds = None if OPAQUE.search(cmd) else shell_split(cmd)
    if not cmds:
        return plain(cmd)
    out = list(cmd)
    for words in cmds:
        names = [w[2] for w in words]
        name = names[0]
        if "/" in name and os.path.basename(name).removesuffix(".py") in ("squad-seal", "squad-turn"):
            name = os.path.basename(name).removesuffix(".py")
        if name not in INERT:
            return plain(cmd)
        data = set()
        if name in ("echo", "printf"):
            data = set(range(1, len(words)))
        else:
            k, sub = 1, ""
            while k < len(names):
                if names[k] in ("-C", "-R", "--repo", "--git-dir", "--work-tree"):
                    k += 2
                elif names[k].startswith("-"):
                    k += 1
                else:
                    sub = names[k]
                    break
            if (name == "git" and ("-c" in names or sub not in GIT_SAFE)) or (name == "gh" and sub not in GH_SAFE):
                return plain(cmd)
            for k, w in enumerate(names[1:], 1):
                if w in DATA_OPTS and k + 1 < len(words):
                    data.add(k + 1)
                elif w.startswith("--") and w.split("=", 1)[0] in DATA_OPTS and "=" in w:
                    data.add(k)
        for k, (s, e, _) in enumerate(words):
            if k in data:
                out[s:e] = " " * (e - s)
            elif "$" in cmd[s:e]:
                return plain(cmd)
    return plain("".join(out))


def merge_target(args):
    """(target, repo) of one `gh pr merge`, from its words after `merge`: the PR
    number, URL or branch ("" for the current branch's PR) and the --repo value.
    None when this reader cannot tell for sure: an unknown flag, more than one
    argument, a flag with no value, a value it does not accept."""
    target, repo, i = [], "", 0
    while i < len(args):
        w = args[i]
        i += 1
        if w == "--":
            target += args[i:]
            break
        if w.startswith("--"):
            name, eq, val = w.partition("=")
            if name in MERGE_VALUED:
                if not eq:
                    if i >= len(args):
                        return None
                    val, i = args[i], i + 1
                if name == "--repo":
                    repo = val
            elif name not in MERGE_BOOL:
                return None
        elif w.startswith("-") and len(w) > 1:
            for j, c in enumerate(w[1:], 2):               # -sd, -t subject, -tsubject, -sRo/r
                if "-" + c in MERGE_BOOL:
                    continue
                if "-" + c not in MERGE_VALUED:
                    return None
                val = w[j:]
                if not val:
                    if i >= len(args):
                        return None
                    val, i = args[i], i + 1
                if c == "R":
                    repo = val
                break
        else:
            target.append(w)
    if len(target) > 1:
        return None
    t = target[0] if target else ""
    t = t[1:] if re.fullmatch(r"#\d+", t) else t
    if t and not (t.isdigit() or PR_URL.fullmatch(t) or (BRANCH.fullmatch(t) and not t.startswith("-"))):
        return None
    if repo and not (t and GH_REPO.fullmatch(repo)):
        return None               # gh itself refuses --repo with no PR named
    return t, repo


def merge_targets(cmd):
    """(target, repo) or None for each `gh pr merge` that is a simple command of
    its own, in order; None for the whole line if it cannot be read word by word."""
    cmds = None if OPAQUE.search(cmd) else shell_split(cmd)
    if cmds is None:
        return None
    out = []
    for words in cmds:
        names = [w[2] for w in words]
        if os.path.basename(names[0]) == "gh" and names[1:3] == ["pr", "merge"]:
            out.append(merge_target(names[3:]))
    return out


def turn_kind(p):
    """What the call has to do with the merge turn: (cli, verb, pr) | (merge,
    shown, target, dir) | (push, source, dir) | (many, what) when one call names
    more than one merge. target is (PR, repo) for gh pr view, or None when the
    watcher cannot tell which PR the call merges; shown is only for naming it;
    dir is where the call runs (see run_dir), None when the watcher cannot tell."""
    tool = str(p.get("tool_name") or "")
    inp = p.get("tool_input") or {}
    if tool.endswith("merge_pull_request"):
        n = str(inp.get("pullNumber") or inp.get("pull_number") or "")
        repo = f"{inp.get('owner') or ''}/{inp.get('repo') or ''}"
        repo = repo if GH_REPO.fullmatch(repo) else ""
        return ("merge", n, (n, repo) if n.isdigit() and (repo or not inp.get("repo")) else None,
                str(p.get("cwd") or ""))
    if tool != "Bash":
        return None
    cmd = str(inp.get("command") or "")
    cwd = str(p.get("cwd") or "")
    text = merge_text(cmd)
    found = []
    merges = list(PR_MERGE.finditer(text))
    targets = merge_targets(cmd) if merges else []
    for i, m in enumerate(merges):
        # the regex finds the merge anywhere (bash -c, ssh, xargs...); which PR it merges is read
        # only from a plain `gh pr merge` command, and only when every merge found is one
        target = targets[i] if targets is not None and len(targets) == len(merges) else None
        found.append(("merge", m.group(2) or m.group(3) or "", target, run_dir(text, m.start(), cwd)))
    for m in API_MERGE.finditer(text):
        found.append(("merge", m.group(1) or "", (m.group(1), "") if m.group(1) else None,
                      run_dir(text, m.start(), cwd)))
    for m in GIT_PUSH.finditer(text):
        where = run_dir(text, m.start(), cwd, re.findall(r"-C[ \t]+(\S+)", m.group(1)))
        src = push_source(m.group(2), where)
        if src is not None:
            found.append(("push", src, where))
    found = list(dict.fromkeys(found))
    if len(found) > 1:
        return ("many", ", ".join(f"PR #{f[1]}" if f[0] == "merge" and f[1] else
                                  "a PR" if f[0] == "merge" else "a push to the trunk" for f in found))
    if found:
        return found[0]
    m = TURN_CLI.search(text)
    return ("cli", m.group(1), m.group(2) or "") if m else None


def trunks(cwd):
    """Branches that count as the trunk, in order: `git config squad.trunk` (a
    comma-separated list), the remote's default branch (origin/HEAD, or gh when
    that ref is missing), then main and master."""
    names = git_rc(cwd, "config", "--get", "squad.trunk")[1].split(",")
    rc, head = git_rc(cwd, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if rc == 0 and head.startswith("origin/"):
        names.append(head[len("origin/"):])
    elif git_rc(cwd, "remote", "get-url", "origin")[0] == 0:
        try:
            r = subprocess.run([os.environ.get("SQUAD_GH") or "gh", "repo", "view", "--json", "defaultBranchRef",
                                "-q", ".defaultBranchRef.name"], capture_output=True, text=True, timeout=8,
                               cwd=cwd, stdin=subprocess.DEVNULL)
            names.append(r.stdout.strip() if r.returncode == 0 else "")
        except (OSError, subprocess.TimeoutExpired):
            pass
    names = [n.strip().removeprefix("refs/heads/") for n in names + ["main", "master"]]
    return [n for n in dict.fromkeys(names) if BRANCH.fullmatch(n) and not n.startswith("-")]


def run_dir(text, end, cwd, dirs=()):
    """The directory the command ending at text[:end] runs in: the session's cwd,
    moved by each `cd` before it and then by each `git -C` (dirs). None when the
    watcher cannot tell: a variable or quotes in the path, `cd -`, a subshell,
    pushd/popd, GIT_DIR, --git-dir, env -C, a directory that does not exist."""
    before = text[:end]
    if ELSEWHERE.search(before):
        return None
    cds = list(CD.finditer(before))
    if cds and re.search(r"[()]", before):
        return None               # a cd inside a subshell may not apply here
    where = cwd
    for words in [m.group(1).split()[:1] or ["~"] for m in cds] + [[d] for d in dirs]:
        w = words[0]
        if w == "-" or not LITERAL_DIR.fullmatch(w):
            return None
        w = os.path.expanduser(w)
        if not os.path.isabs(w) and not where:
            return None
        where = os.path.normpath(os.path.join(where, w))
    return where if not (cds or dirs) or os.path.isdir(where) else None     # a failed cd: who knows


def push_source(args, where):
    """The local revision a `git push` run in `where` sends to the trunk (see
    trunks); None if it does not push to the trunk. Any word may be the refspec
    (in doubt, it is); `HEAD` alone is the current branch; --all and --mirror
    push the trunk too; with no refspec, the current branch is pushed, to the
    trunk if it is the trunk or if its push target is. `where` None: the watcher
    cannot tell the repository, its trunk or its branch, so any push counts."""
    if where is None:
        return "HEAD"
    trunk = trunks(where) if where else ["main", "master"]
    words = args.split()
    if "--all" in words or "--mirror" in words:
        return trunk[0]
    refs = [w for w in words if not w.startswith("-")]
    current = git_rc(where, "branch", "--show-current")[1] if where else ""
    for ref in refs:
        src, colon, dst = ref.lstrip("+").rpartition(":")
        if not colon and dst in ("HEAD", "@"):
            dst, src = current, "HEAD"
        if dst.removeprefix("refs/heads/") in trunk:
            return src if colon or src == "HEAD" else dst
    if len(refs) <= 1 and where:
        target = git_rc(where, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{push}")[1]
        if current in trunk or target.partition("/")[2] in trunk:
            return "HEAD"
    return None


def git_rc(cwd, *args, timeout=5):
    """(returncode, stdout) of a git command in cwd; (-1, "") if it could not run or timed out."""
    try:
        r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
        return r.returncode, r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return -1, ""


def turn_open(repo):
    os.makedirs(TURN, exist_ok=True)
    path = os.path.join(TURN, hashlib.sha1(repo.encode()).hexdigest()[:16] + ".json")
    lock = open(path + ".lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    d = load(path)
    d["repo"] = repo
    d.pop("queue", None)          # the long queue of earlier versions: nobody waits in line any more
    if not isinstance(d.get("intents"), list):
        d["intents"] = []
    return path, d, lock


def turn_mark(session, repo=None):
    """Cheap marker that the session holds a turn: avoids opening the turn file on every call."""
    path = os.path.join(TURN, f"s-{safe(session)}")
    try:
        if repo:
            os.makedirs(TURN, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(repo)
        else:
            os.remove(path)
    except OSError:
        pass


def turn_note(session, text):
    """Note for ANOTHER session: its own append-only file, so as not to fight
    that session's hook over its state."""
    try:
        with open(os.path.join(STATE, f"{safe(session)}.notes"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(text) + "\n")
    except OSError:
        pass


def turn_notes(session):
    path = os.path.join(STATE, f"{safe(session)}.notes")
    if not os.path.exists(path):
        return []
    tmp = f"{path}.{os.getpid()}"
    try:
        os.replace(path, tmp)
        with open(tmp, encoding="utf-8") as fh:
            notes = [json.loads(line) for line in fh if line.strip()]
        os.remove(tmp)
        return [n for n in notes if isinstance(n, str)]
    except (OSError, ValueError):
        return []


def gh_pr(cwd, pr, field):
    """One field of the PR through gh; with no number, the current branch's PR. Empty if it failed."""
    if pr and not str(pr).isdigit():
        return ""
    try:
        r = subprocess.run([os.environ.get("SQUAD_GH") or "gh", "pr", "view", *([str(pr)] if pr else []),
                            "--json", field, "-q", "." + field], capture_output=True, text=True, timeout=8,
                           cwd=cwd if cwd and os.path.isdir(cwd) else None, stdin=subprocess.DEVNULL)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def pr_info(cwd, target, repo=""):
    """Number, base branch and head (branch and SHA) of the PR the merge names
    (number, URL or branch, from merge_target; "" for the current branch's PR),
    in --repo if it named one, through gh; empty fields for whatever gh could
    not tell. Every value is checked before it reaches a git command line."""
    info = {"pr": target if target.isdigit() else "", "base": "", "branch": "", "sha": ""}
    try:
        r = subprocess.run([os.environ.get("SQUAD_GH") or "gh", "pr", "view", *([target] if target else []),
                            *(["--repo", repo] if repo else []),
                            "--json", "number,baseRefName,headRefName,headRefOid"], capture_output=True,
                           text=True, timeout=10, cwd=cwd if cwd and os.path.isdir(cwd) else None,
                           stdin=subprocess.DEVNULL)
        d = json.loads(r.stdout) if r.returncode == 0 else {}
    except (OSError, subprocess.TimeoutExpired, ValueError):
        d = {}
    if not isinstance(d, dict):
        d = {}
    if not info["pr"] and str(d.get("number") or "").isdigit():
        info["pr"] = str(d["number"])
    for key, field in (("base", "baseRefName"), ("branch", "headRefName")):
        v = str(d.get(field) or "")
        info[key] = v if BRANCH.fullmatch(v) and not v.startswith("-") else ""
    v = str(d.get("headRefOid") or "")
    info["sha"] = v if SHA.fullmatch(v) else ""
    if not info["pr"] and not target:
        n = gh_pr(cwd, "", "number")
        info["pr"] = n if n.isdigit() else ""
    return info


def turn_entry(p, pr="", branch=""):
    cwd = str(p.get("cwd") or "")
    if not branch:
        branch = git_rc(cwd, "branch", "--show-current")[1] if cwd else ""
    now = time.time()
    return {"session": safe(p.get("session_id")), "pr": pr if str(pr).isdigit() else "",
            "branch": branch if BRANCH.fullmatch(branch or "") else "", "cwd": cwd,
            "since": now, "asked": now}


def who(e):
    return f"session {e['session'][:8]}" + (f" (PR #{e['pr']})" if e.get("pr") else "") + (
        f", branch {e['branch']}" if e.get("branch") else "")


def turn_release(d, why):
    h = d.get("holder")
    if not h:
        return
    d["last"] = {"session": h["session"], "pr": h.get("pr"), "branch": h.get("branch"),
                 "at": time.time(), "why": why}
    d["holder"] = None
    turn_mark(h["session"])


def turn_settle(d, me=""):
    """Expires a turn whose merge call never came back, and old intents."""
    now = time.time()
    h = d.get("holder")
    if h and now - h.get("since", 0) > TURN_HOLD:
        turn_release(d, "expired")
        if h["session"] != me:
            turn_note(h["session"], f"[squad-watch] MERGE QUEUE: your merge turn in {d['repo']} expired: the "
                      f"merge call did not come back within {TURN_HOLD} s. If the PR did not land, run the merge again.")
    d["intents"] = [e for e in d["intents"] if isinstance(e, dict) and now - e.get("asked", 0) < INTENT_TTL]


def seal_on(cwd):
    """The seal is opt-in per repository (`git config squad.seal true`) or by SQUAD_SEAL=1."""
    env = os.environ.get("SQUAD_SEAL")
    if env in ("0", "1"):
        return env == "1"
    rc, out = git_rc(cwd, "config", "--get", "--bool", "squad.seal")
    return out == "true" or rc == -1          # git did not answer: in doubt the seal is on (fail closed)


def seal_load(path):
    d = load(path)
    return d if d.get("verdict") == "SHIP" and SHA.fullmatch(str(d.get("sha") or "")) else {}


SEAL_HOW = ("Where the work continues: the verifier reviews this exact commit; once it returns SHIP, in the card's "
            "worktree, with a clean tree at that commit, `squad-seal record --card <id> --model <name> --verdict "
            "SHIP --evidence <path>` and repeat the merge. `squad-seal show` shows the seal of HEAD.")


def seal_denial(repo, sha, what, branch):
    """Empty if the SHA has a SHIP seal; otherwise the denial, saying how to seal."""
    folder = os.path.join(SEALS, hashlib.sha1(repo.encode()).hexdigest()[:16])
    how = SEAL_HOW
    if not sha:
        return (f"[squad-watch] MERGE SEAL: the seal is on in this repository and the watcher could not read the "
                f"SHA of {what} (gh or git did not answer), so the seal cannot be checked. Check `gh pr view` "
                "(or the ref you push), then repeat the merge. " + how)
    seal = seal_load(os.path.join(folder, f"{sha}.json"))
    if seal.get("sha") == sha:
        return ""
    other = {}
    if branch and os.path.isdir(folder):
        for name in os.listdir(folder):
            s = seal_load(os.path.join(folder, name)) if name.endswith(".json") else {}
            if s.get("branch") == branch and str(s.get("at") or "") > str(other.get("at") or ""):
                other = s
    return (f"[squad-watch] MERGE SEAL: {what} is at {sha[:12]} and there is no seal for that SHA"
            + (f"; the seal of branch {branch} is for {other['sha'][:12]} (card {other.get('card')}, "
               f"{other.get('at')}): the branch moved after the verification" if other else "")
            + ". A seal records that this exact commit was verified with SHIP. " + how)


def conflict_denial(cwd, info, sealed):
    """Fetches the base and test-merges the PR head into it, without touching
    any worktree. Empty if it merges cleanly or if the check could not run."""
    base, sha, pr = info["base"], info["sha"], info["pr"]
    git_rc(cwd, "fetch", "-q", "origin", f"+refs/heads/{base}:refs/remotes/origin/{base}", timeout=20)
    if git_rc(cwd, "cat-file", "-e", f"{sha}^{{commit}}")[0] != 0:
        for ref in ([info["branch"]] if info["branch"] else []) + ([f"pull/{pr}/head"] if pr else []):
            git_rc(cwd, "fetch", "-q", "origin", ref, timeout=20)
            if git_rc(cwd, "cat-file", "-e", f"{sha}^{{commit}}")[0] == 0:
                break
    if git_rc(cwd, "rev-parse", "--verify", "-q", f"origin/{base}^{{commit}}")[0] != 0:
        return ""                 # no such base here: nothing to test against
    rc, out = git_rc(cwd, "merge-tree", "--write-tree", "--name-only", f"origin/{base}", sha, timeout=20)
    if rc != 1 or not SHA.fullmatch(out.split("\n", 1)[0]):
        return ""                 # 0: merges cleanly; anything else (old git, missing commit): fails open
    files = []
    for f in out.splitlines()[1:]:
        if not f.strip():
            break                 # after the blank line come the informational messages
        if f not in files:
            files.append(f)
    listed = ", ".join(files[:12]) + (f" and {len(files) - 12} more" if len(files) > 12 else "")
    return (f"[squad-watch] MERGE CONFLICT: PR #{pr or '?'}" + (f" ({info['branch']})" if info["branch"] else "")
            + f" does not merge cleanly into origin/{base} as it is now, after a fetch. Conflict in: "
            f"{listed or 'files git did not name'}. The merge was not attempted and the turn was released. Where "
            f"the work continues: in the card's worktree, `git fetch origin && git merge origin/{base}`, resolve "
            "those files, run the suite, push, and send the card through verification again in AgenFK"
            + (", then record a new seal for the new HEAD (`squad-seal record ...`)" if sealed else "")
            + "; then merge. Syncing with main is never denied.")


def merge_gate(kind, cwd, repo, info):
    """Checks that run while the turn is held, right before the merge call."""
    sealed = seal_on(cwd)
    if kind[0] == "push":
        if not sealed:
            return ""             # a push to the trunk is fast-forward only: git itself refuses a conflict
        src = kind[1]
        sha = git_rc(cwd, "rev-parse", "--verify", "-q", f"{src}^{{commit}}")[1] if (
            src and BRANCH.fullmatch(src) and not src.startswith("-")) else ""     # cwd is already where it runs
        branch = git_rc(cwd, "branch", "--show-current")[1]
        return seal_denial(repo, sha if SHA.fullmatch(sha) else "", f"the push to the trunk ({src or '?'})", branch)
    if sealed and kind[2] is None:
        return ("[squad-watch] MERGE SEAL: the seal is on and the watcher cannot tell which PR this call merges "
                f"({'PR #' + kind[1] if kind[1] else 'no PR it can read'}): the merge is not a plain `gh pr merge "
                "[<number> | <url> | <branch>]` with the flags of `gh pr merge --help`, so the seal cannot be "
                "checked. Run the merge as its own command, `gh pr merge <number> [--repo owner/repo] [--squash]`, "
                "from the card's worktree. " + SEAL_HOW)
    if sealed:
        why = seal_denial(repo, info["sha"], f"the head of PR #{info['pr'] or '?'}", info["branch"])
        if why:
            return why
    if info["sha"] and info["base"]:
        return conflict_denial(cwd, info, sealed)
    return ""


def turn_pre(p):
    """Merge turn on PreToolUse. Returns True if it denied the call.

    The turn covers only the merge call itself: taken here, released by the
    PostToolUse of the same call (success or failure), expired after TURN_HOLD.
    Requesting and syncing never block anyone."""
    kind = turn_kind(p)
    if not kind or os.environ.get("SQUAD_TURN") == "0":
        return False
    cwd = str(p.get("cwd") or "")
    if kind[0] in ("merge", "push"):
        if kind[-1] is None:      # a cd or -C the watcher cannot follow: the seal may be on over there
            if os.environ.get("SQUAD_SEAL") != "0" and (not git_dir(cwd) or seal_on(cwd)):
                deny("[squad-watch] MERGE SEAL: the watcher cannot tell which repository this "
                     f"{'push' if kind[0] == 'push' else 'merge'} runs in (a cd or -C to a variable or a quoted "
                     "path, `cd -`, a subshell, pushd, GIT_DIR or env -C before it), so the seal there cannot be "
                     "checked. Run it with a literal path: `cd /path/to/worktree && gh pr merge <number>`, or "
                     "`git -C /path/to/worktree push ...`. " + SEAL_HOW)
                return True
        else:
            cwd = kind[-1]        # `cd <dir> &&` or `git -C <dir> push`: the repository is that one
    repo = git_dir(cwd)
    if not repo:
        if kind[0] in ("merge", "push", "many") and os.environ.get("SQUAD_SEAL") == "1":
            deny("[squad-watch] MERGE SEAL: SQUAD_SEAL=1 and this merge does not run inside a git repository, so "
                 "the seal cannot be checked. Run the merge from the card's worktree.")
            return True
        return False
    if kind[0] == "many":
        deny(f"[squad-watch] MERGE QUEUE: this call names more than one merge ({kind[1]}), so the turn, the "
             "conflict check and the seal cannot tell which one to check. Run one merge per call: split the "
             "command, or move text that only mentions a merge into a -m/--body/--description value.")
        return True
    me = safe(p.get("session_id"))
    info = {"pr": "", "base": "", "branch": "", "sha": ""}
    if kind[0] == "merge" and kind[2] is not None:
        info = pr_info(cwd, *kind[2])
    path, d, lock = turn_open(repo)
    denied = ""
    try:
        turn_settle(d, me)
        h = d.get("holder")
        if kind[0] == "cli":
            if kind[1] in ("request", "release"):
                d["intents"] = [e for e in d["intents"] if e.get("session") != me]
            if kind[1] == "request":
                d["intents"].append(turn_entry(p, kind[2]))
            elif kind[1] == "release" and h and h["session"] == me:
                turn_release(d, "released")
        elif h and h["session"] != me:
            denied = (f"[squad-watch] MERGE QUEUE: {who(h)} is merging in this repository right now (for "
                      f"{int(time.time() - h['since'])} s). The turn covers only the merge call and expires after "
                      f"{TURN_HOLD} s: repeat the merge in a few seconds. There is no queue to join and no need to "
                      "sync with main because of this.")
        else:
            d["holder"] = turn_entry(p, info["pr"], info["branch"])
            d["intents"] = [e for e in d["intents"] if e.get("session") != me]
            turn_mark(me, repo)
        save(path, d)
    finally:
        lock.close()
    if not denied and kind[0] in ("merge", "push"):
        denied = merge_gate(kind, cwd, repo, info)
        if denied:
            path, d, lock = turn_open(repo)
            try:
                if (d.get("holder") or {}).get("session") == me:
                    turn_release(d, "denied")
                save(path, d)
            finally:
                lock.close()
    if denied:
        deny(denied)
    return bool(denied)


def turn_post(p):
    """After the call (success or failure): the merge call gives the turn back."""
    session = safe(p.get("session_id"))
    mark = os.path.join(TURN, f"s-{session}")
    if not os.path.exists(mark):
        return []
    try:
        with open(mark, encoding="utf-8") as fh:
            repo = fh.read().strip()
    except OSError:
        return []
    kind = turn_kind(p)
    path, d, lock = turn_open(repo)
    try:
        h = d.get("holder")
        if not h or h["session"] != session:
            turn_mark(session)
        elif kind and kind[0] in ("merge", "push"):
            turn_release(d, "done")
        save(path, d)
    finally:
        lock.close()
    return []


# -------------------------------------------------------------------- events
def pre_tool(p):
    agent = p.get("agent_id")
    kind = turn_kind(p)
    try:
        if kind and turn_pre(p):
            return
    except Exception as exc:
        # With the seal on, a check that broke denies: it never passes by omission.
        if kind and kind[0] in ("merge", "push", "many") and os.environ.get("SQUAD_TURN") != "0" and (
                seal_on(str(p.get("cwd") or ""))):
            deny(f"[squad-watch] MERGE SEAL: the seal is on and the merge check failed ({type(exc).__name__}), "
                 "so the merge is denied rather than let through unchecked. Where the work continues: run "
                 "`squad-seal show` and `gh pr view` in the card's worktree to see what is failing, fix it, and "
                 "repeat the merge; if it keeps failing, the decision is the owner's.")
            return
        raise
    if not agent:
        if p.get("tool_name") in DISPATCH:
            pre_dispatch(p)
        return
    st = load(state_path(p.get("session_id"), agent))
    tool = p.get("tool_name") or ""
    if st.get("cut"):
        if tool == "Bash" and closing_command(str((p.get("tool_input") or {}).get("command") or ""),
                                                 str(p.get("cwd") or "")):
            return
        deny(f"[squad-watch] HANDOFF: this sub-session is at {k(st.get('ctx', 0))} tokens of "
             f"context (ceiling {k(CTX_CUT)}). No tool other than git/agenfk comment "
             f"is allowed. {RETURN_HANDOFF}")
        return
    h, calls = call_hash(p), st.get("calls") or []
    if tool not in MUTATING and (calls.count(h) >= DENY_AT - 1 or streak(calls, h) >= STREAK_DENY):
        st["denied"] = st.get("denied", 0) + 1
        save(state_path(p.get("session_id"), agent), st)
        deny(f"[squad-watch] LOOP: this same {tool} call has already run {calls.count(h)}x with no "
             "edit in between and the result is not going to change. Use the result that is already in the "
             "context and change approach; if there is no other approach, stop. " + RETURN_HANDOFF)


def post_tool(p):
    session, agent = p.get("session_id"), p.get("agent_id")
    path = state_path(session, agent)
    st = load(path)
    tool = p.get("tool_name") or ""
    out = []
    if tool in MUTATING:
        st["calls"] = []          # the state changed: repeating a read/test makes sense again
    else:
        h = call_hash(p)
        calls = (st.get("calls") or []) + [h]
        st["calls"] = calls[-WINDOW:]
        n = st["calls"].count(h)
        if n in (WARN_AT, DENY_AT):
            st["loop_warned"] = True
            out.append(f"[squad-watch] LOOP: same {tool} call {n}x in the last {WINDOW}, "
                       "with no edit in between. Do not repeat it: say what the result already showed and "
                       "change approach or ask.")
    st["n"] = st.get("n", 0) + 1
    if tool in DISPATCH and not agent:
        st["subs"] = st.get("subs", 0) + 1
        key = review_key(p)
        if key:
            rev = st.setdefault("rev", {})
            rev[key] = rev.get(key, 0) + 1
            if rev[key] == 3 and not key.endswith(":no-card"):
                out.append(f"[squad-watch] 3rd reviewer round for {key}. The rule is at most 2 "
                           f"correction rounds; dispatch number {MAX_REV + 1} is denied. If the same "
                           "failure came back, the decision is the owner's.")
        if st["subs"] == int(MAX_SUBS * 0.6):
            out.append(f"[squad-watch] {st['subs']} sub-sessions dispatched in this session (ceiling "
                       f"{MAX_SUBS}). Prepare the handoff: the rest goes to a new session.")

    now = time.time()
    if now - st.get("checked", 0) >= CHECK_EVERY:
        st["checked"] = now
        tok = fold(sub_transcript(p) if agent else (p.get("transcript_path") or ""), st.get("tok") or {})
        st["tok"] = tok
        if tok["req"]:
            window = 0 if agent else main_window(session)
            c = ctx_lib().handoff_math(tok["inp"], tok["wr"], tok["rd"], tok["out"], tok["ctx"], window)
            ctx = tok["ctx"]
            st.update(ctx=ctx, burn=c["burn"], ratio=c["ratio"])
            if agent:
                if ctx >= CTX_CUT and not st.get("cut"):
                    st["cut"] = True
                    out.append(f"[squad-watch] HANDOFF NOW: context {k(ctx)} >= ceiling {k(CTX_CUT)} "
                               f"({figures(c, ctx)}). The next tools will be denied. {RETURN_HANDOFF}")
                elif c["due"] and not st.get("ratio_warned"):
                    st["ratio_warned"] = True
                    out.append(f"[squad-watch] HANDOFF: {figures(c, ctx)}; context {k(ctx)}. This "
                               f"sub-session already spends more rereading than producing. Finish the "
                               f"current step and do not start another. {RETURN_HANDOFF}")
                elif ctx >= CTX_WARN and not st.get("ctx_warned"):
                    st["ctx_warned"] = True
                    out.append(f"[squad-watch] context {k(ctx)} (warning at {k(CTX_WARN)}, cut at "
                               f"{k(CTX_CUT)}; {figures(c, ctx)}). Close what is open, do not start a "
                               "new front and stop rereading files that are already in the context.")
                if c["burn"] >= BURN_WARN and not st.get("burn_warned"):
                    st["burn_warned"] = True
                    out.append(f"[squad-watch] burn {k(c['burn'])} weighted (limit {k(BURN_WARN)}). The "
                               "card is bigger than one sub-session: finish the current step and send back "
                               "what remains as scope.")
            else:
                # The decision is this arithmetic and nothing else: level 2 = handoff, level 1 = notice with no action.
                pct = 100.0 * ctx / window
                level = (2 if (pct >= MAIN_PCT or c["due"] or (MAIN_HANDOFF and ctx >= MAIN_HANDOFF))
                         else 1 if (ctx >= c["floor_min"] or (MAIN_WARN and ctx >= MAIN_WARN)) else 0)
                # the level went up, or it keeps growing after the alert: reminds every 50k
                again = level == 2 and ctx >= st.get("alert_ctx", 0) + 50_000
                if level > st.get("ctx_level", 0) or again:
                    st["alert_ctx"] = ctx
                    if level == 2:
                        st.setdefault("alert_ts", now)
                    head = (f"context {k(ctx)}/{k(window)} ({pct:.0f}%), burn {c['burn_pct']:.0f}% of the "
                            f"budget, {figures(c, ctx)}")
                    if level == 2:
                        out.append(
                            f"[squad-watch] PROACTIVE HANDOFF — {head}. When you close the step in progress, without "
                            "asking permission and without starting a new front: (1) record on the card what was "
                            "decided (`agenfk comment <id> \"PAUSE: done X, remaining Y, next Z\"`); "
                            "(2) write the handoff with mode A of the `clear-pickup` skill (ground truth by "
                            "command, short, UNKNOWN for whatever you did not verify; under Next step, what "
                            "remains of the current request, in order); (3) end your reply with the handoff "
                            "path and stop. " + (
                                "The watcher clears this session and calls the pickup on its own: the work continues "
                                "in the new session, not here." if can_switch() else
                                "Tell the owner: `/clear` and then `/clear-pickup pickup`."))
                    else:
                        out.append(f"[squad-watch] {head}. Informational only: KEEP working normally "
                                   "and do NOT write a handoff on your own. The handoff is decided by the watcher, "
                                   f"by arithmetic: context at {MAIN_PCT}% of the window, or reread >= {cx_share():.0%} with "
                                   f"context >= {k(c['floor'])} (the floor for the current burn; it drops to "
                                   f"{k(c['floor_min'])} as the burn rises). When it gets there, you receive "
                                   "PROACTIVE HANDOFF.")
                if level < st.get("ctx_level", 0) and not st.get("ordered") and not st.get("switched"):
                    # alert raised by an old rule (or a context that shrank): undone in writing
                    out.append(f"[squad-watch] ALERT CANCELLED — context {k(ctx)}/{k(window)} ({pct:.0f}%), "
                               f"reread {c['share']:.0%}: below the current threshold (context >= {MAIN_PCT}% of the "
                               f"window, or reread >= {cx_share():.0%} with context >= {k(c['floor'])}). The earlier notice or "
                               "handoff order NO longer applies: keep working normally, you may open "
                               "a new front, and do not write a handoff without a new PROACTIVE HANDOFF.")
                    for key in ("alert_ts", "alert_ctx", "nudges"):
                        st.pop(key, None)
                st["ctx_level"] = 2 if st.get("ordered") else level   # a handoff already ordered does not disarm
                out += dispatch_notice(session, st, ctx)
    if not agent and st.get("wait_slot") and other_orchestrators(session) < MAX_ORCH:
        st.pop("wait_slot")
        out.append("[squad-watch] SLOT FREE: there is an orchestrator slot again. The dispatch that was denied "
                   "for lack of a slot (the reviewer, or the next card) can now go through an agent.")
    out += turn_post(p)
    if not agent:
        out += turn_notes(session)
    if not agent and st.get("pending"):
        out += st["pending"]
        st["pending"] = []
    save(path, st)
    emit("PostToolUse", "\n".join(out))


def subagent_stop(p):
    session, agent = p.get("session_id"), p.get("agent_id")
    if not agent:
        return
    cx = ctx_lib()
    spath = state_path(session, agent)
    st = load(spath)
    m = measure(sub_transcript(p))
    if not m:                     # internal agent, with no transcript of its own: nothing to measure
        try:
            os.remove(spath)
        except OSError:
            pass
        return
    kind = cx.clean(p.get("agent_type") or "?", 40)
    row = {"ts": time.time(), "session": safe(session), "agent_id": safe(agent), "agent_type": kind,
           "cwd": cx.clean(m.get("cwd") or p.get("cwd")), "model": cx.clean(m.get("model"), 60),
           "ctx": m.get("ctx", 0), "ctx_pct": round(100.0 * m.get("ctx", 0) / CTX_CUT, 1),
           "burn": m.get("burn", 0), "reread": m.get("reread", 0.0), "ratio": m.get("ratio", 0.0),
           "calls": m.get("calls", 0),
           "started": m.get("started"), "ended": m.get("last"),
           "loop_warned": bool(st.get("loop_warned")), "denied": st.get("denied", 0),
           "cut": bool(st.get("cut"))}
    os.makedirs(BASE, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.chmod(LOG, 0o600)

    bad = []
    if row["cut"]:
        bad.append(f"cut at the context ceiling ({k(row['ctx'])})")
    elif row["ctx"] >= CTX_WARN:
        bad.append(f"context {k(row['ctx'])}")
    if row["denied"] or row["loop_warned"]:
        bad.append(f"loop ({row['denied']} call(s) denied)")
    if row["burn"] >= BURN_WARN:
        bad.append(f"burn {k(row['burn'])}")
    if row["reread"] >= cx.REREAD_SHARE and row["ctx"] >= 2 * cx.CTX_BASE:
        bad.append(f"reread {row['reread']:.0%}")
    if bad:
        mpath = state_path(session, "")
        main = load(mpath)
        main.setdefault("pending", []).append(
            f"[squad-watch] sub-session `{kind}` {safe(agent)[:8]} ended with: {'; '.join(bad)}. "
            "Do not redispatch the same brief: read its return handoff, check in git what "
            "got done, and dispatch only what REMAINS in a new sub-session with a short brief "
            "(card, branch, worktree, files, next step) — or split the card. At most 1 redispatch.")
        main["pending"] = main["pending"][-5:]
        save(mpath, main)
    try:
        os.remove(spath)
        cutoff = time.time() - 2 * 86400
        for name in os.listdir(STATE):
            f = os.path.join(STATE, name)
            if os.path.getmtime(f) < cutoff:
                os.remove(f)
    except OSError:
        pass


HANDOFF_PATH = re.compile(r"[A-Za-z0-9_./-]+/handoffs/[A-Za-z0-9_.-]+\.md")


def own_handoff(transcript, since):
    """The handoff THIS session wrote: its last Write to .../handoffs/*.md, a
    regular file owned by the user, written after the alert, and whose content
    on disk is byte for byte what the session wrote (returns path and sha256).
    A record with no content, a denied Write or a file changed afterwards by
    another process does not pass. Any other file in the folder (from another
    session, from a sub-agent, arrived in a pull) will not do: the new session
    is going to execute whatever is written in it without the owner looking."""
    try:
        with open(transcript, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 3_000_000))
            lines = fh.read().split(b"\n")
    except OSError:
        return None
    for raw in reversed(lines):
        if b"handoffs/" not in raw or b'"Write"' not in raw:
            continue
        try:
            rec = json.loads(raw)
            if rec.get("type") != "assistant" or rec.get("isSidechain") is not False:
                continue
            blocks = (rec.get("message") or {}).get("content") or []
        except (ValueError, AttributeError):
            continue
        for b in blocks:
            if not (isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Write"):
                continue
            path = str((b.get("input") or {}).get("file_path") or "")
            content = (b.get("input") or {}).get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            if not HANDOFF_PATH.fullmatch(path) or not os.path.isabs(path) or ".." in path.split("/"):
                continue
            try:
                info = os.lstat(path)
            except OSError:
                continue
            import stat as _stat
            if not (_stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and info.st_mtime >= since - 5):
                return None            # the last handoff Write is the one that counts; it does not fall back to an old one
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            try:
                with open(path, "rb") as fh:
                    same = hashlib.sha256(fh.read()).hexdigest() == digest
            except OSError:
                same = False
            return (path, digest) if same else None
    return None


def can_switch():
    return bool(os.environ.get("HERDR_PANE_ID")) and os.environ.get("SQUAD_SWITCH") != "0"


# Bilingual on purpose: these read what the owner types, in Portuguese or English.
RESUME = re.compile(r"clear-pickup\s+pickup|\bretom|\bresum|\bpick\s+(?:it\s+|this\s+)?(?:back\s+)?up\b", re.I)
ASKED_TO_STOP = re.compile(r"handoff|hand-off|pickup|/clear|pausa|pausar|encerr|fechar o dia|por hoje|pode parar"
                           r"|pause|wrap(?:ping)?\s+(?:it\s+|this\s+)?up|stop for today|for today"
                           r"|call it a day|close the day|you can stop", re.I)


def prompt(p):
    """Records the time of the owner's request and whether the owner asked for a
    handoff/pause. A sub-agent's return arrives through the same event and
    mentions "handoff" in its text: that is not the owner speaking. And
    `/clear-pickup pickup` is a request to resume, not to stop."""
    text = str(p.get("prompt") or "")
    if text.lstrip().startswith("<task-notification>"):
        return
    path = state_path(p["session_id"], "")
    st = load(path)
    st["prompt_ts"] = time.time()
    st["asked_stop"] = bool(ASKED_TO_STOP.search(text)) and not RESUME.search(text)
    st["last_prompt"] = text[:3000]
    st.pop("early_block", None)
    save(path, st)


def git_out(cwd, *args):
    try:
        r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=5,
                           stdin=subprocess.DEVNULL)
        return r.stdout.strip()[:3000] if r.returncode == 0 else "UNKNOWN"
    except (OSError, subprocess.TimeoutExpired):
        return "UNKNOWN"


def watch_handoff(p, st):
    """The session was ordered to write the handoff and stopped without it: the
    watcher takes over. Only what the watcher measures or kept goes in (git, the
    owner's last request, the denied briefs); what was decided in the
    conversation stays UNKNOWN, in writing."""
    session, cwd = safe(p["session_id"]), str(p.get("cwd") or "")
    briefs = os.path.join(BASE, "handoffs", f"{session}-dispatches.md")
    body = f"""# Handoff written by squad-watch

The session received the handoff order and stopped without writing its own. The
watcher does not read the conversation: what was decided in it is UNKNOWN. What
counts is what is below, the card and git.

- **When:** {time.strftime('%Y-%m-%dT%H:%M:%S%z')}
- **Session:** {session} (context {k(st.get('ctx', 0))}, {st.get('blocked', 0)} dispatch(es) denied)
- **Project:** {cwd or 'UNKNOWN'}
- **Transcript:** {p.get('transcript_path') or 'UNKNOWN'}

## Ground truth (commands run by the watcher)

Branch: {git_out(cwd, 'branch', '--show-current')}

`git status --short`:
{git_out(cwd, 'status', '--short') or '(clean)'}

`git log --oneline -5`:
{git_out(cwd, 'log', '--oneline', '-5')}

## Owner's last request

{st.get('last_prompt') or 'UNKNOWN'}

## Denied dispatches

{('Briefs in full, in the order in which they were denied: ' + briefs) if os.path.exists(briefs) else 'None kept.'}

## Next step

1. Check git against what is above and read the card in progress and its comments.
2. If there are denied briefs, they are the plan: execute them in order. Try the dispatch; if the watcher
   denies it, do what the denial says (with a light session, implement right here).
3. With no briefs: continue the owner's last request from what git and the card show as done.
4. If it is not possible to tell what remains, ask the owner before editing.
"""
    path = os.path.join(BASE, "handoffs", f"{session}-watch.md")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.replace(tmp, path)
    except OSError:
        return None
    return path, hashlib.sha256(body.encode("utf-8")).hexdigest()


def early_handoff(p, path, st):
    """The session wrote a handoff and stopped without the watcher ordering it
    and without the owner asking: it was the agent's opinion, below the
    threshold. Sends the work back, once per request."""
    if p.get("stop_hook_active") or st.get("early_block") or st.get("asked_stop") or not st.get("prompt_ts"):
        return
    if not own_handoff(str(p.get("transcript_path") or ""), st["prompt_ts"]):
        return
    st["early_block"] = True
    save(path, st)
    print(json.dumps({"decision": "block", "reason": (
        f"[squad-watch] Handoff out of turn: the context is at {k(st.get('ctx', 0))}, below the threshold, "
        "and neither the watcher nor the owner asked for a handoff. This session will NOT be cleared. Keep "
        "working from right here, following the Next step you have just written. Handoff only when "
        "PROACTIVE HANDOFF or DISPATCH DENIED arrives from the watcher, or when the owner asks.")}))


def stop(p):
    """The main session stopped. At handoff level, either it writes the handoff,
    or (already written) the session switch is launched."""
    if p.get("agent_id"):
        return
    session = p["session_id"]
    path = state_path(session, "")
    st = load(path)
    if st.get("ctx_level", 0) < 2 and not st.get("switched"):
        early_handoff(p, path, st)
        return
    if st.get("switched"):
        return
    if p.get("background_tasks"):         # something is still going to wake this session
        return
    if not st.get("alert_ts"):            # state without the alert time: only a handoff written from now on counts
        st["alert_ts"] = time.time()
        save(path, st)
    since = st["alert_ts"]
    ho = own_handoff(str(p.get("transcript_path") or ""), since)
    if not ho:
        if not st.get("nudges") or (not p.get("stop_hook_active") and st["nudges"] < 2):
            st["nudges"] = st.get("nudges", 0) + 1
            save(path, st)
            print(json.dumps({"decision": "block", "reason": (
                "[squad-watch] This session is at HANDOFF level and stopped without writing the handoff. "
                "Before stopping: comment on the card (`agenfk comment`), write the handoff with mode A of the "
                "`clear-pickup` skill (with the Write tool, in a new file) with what remains of the "
                "current request under Next step, and only then "
                "end with the path of the file.")}))
            return
        if not can_switch():
            return
        ho = watch_handoff(p, st)         # nudged and stopped again without it: the watcher takes over
        if not ho:
            return
    if not can_switch():
        return
    pane = os.environ["HERDR_PANE_ID"]
    st["switched"] = True
    save(path, st)
    switch = os.path.join(os.path.dirname(os.path.realpath(__file__)), "squad-switch.py")
    subprocess.Popen([sys.executable, switch, pane, session, ho[0], ho[1]], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True, close_fds=True)


def main():
    if os.environ.get("SQUAD_WATCH") == "0":
        return
    os.umask(0o077)               # state and metrics mention project paths: only the owner reads them
    p = json.load(sys.stdin)
    if not isinstance(p, dict) or not p.get("session_id"):
        return
    event = p.get("hook_event_name")
    # parallel calls of the same session read and write the same state: one at a time
    os.makedirs(STATE, exist_ok=True)
    for d in (BASE, STATE):       # the umask only applies to what is created now
        if os.stat(d).st_mode & 0o077:
            os.chmod(d, 0o700)
    lock = open(os.path.join(STATE, f".{safe(p['session_id'])}.lock"), "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    if event == "PreToolUse":
        pre_tool(p)
    elif event == "PostToolUse":
        post_tool(p)
    elif event == "PostToolUseFailure":
        turn_post(p)              # a merge call that failed gives the turn back too
    elif event == "SubagentStop":
        subagent_stop(p)
    elif event == "Stop":
        stop(p)
    elif event == "UserPromptSubmit" and not p.get("agent_id"):
        prompt(p)
        emit(event, "\n".join(turn_notes(p["session_id"]) + pending(p["session_id"])))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Fails open on purpose: a defect here must not lock every session on
        # the machine. But it is logged, so the brake does not vanish silently.
        try:
            os.makedirs(BASE, exist_ok=True)
            log = os.path.join(BASE, "watch-errors.log")
            if not os.path.exists(log) or os.path.getsize(log) < 200_000:
                with open(log, "a", encoding="utf-8") as fh:
                    fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {type(exc).__name__}\n")
        except Exception:
            pass
    sys.exit(0)
