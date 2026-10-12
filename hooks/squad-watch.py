#!/usr/bin/env python3
"""Squad sentinel: watches every Claude Code session and sub-session from the inside.

Registered on PreToolUse, PostToolUse, SubagentStop and UserPromptSubmit.

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

Merge queue (one per repository, ~/.claude/squad/turn/): with several sessions
landing PRs at the same time, every merge moves main under the others and the
conflict that was resolved comes back. The turn belongs to one session per
repository:
  merge (`gh pr merge`, direct push to main, merge_pull_request)
      turn free or already yours  passes, and the session keeps the turn
      another session's turn      denied; the session joins the queue and is called
                                  (MERGE TURN, a note in the session and a prompt
                                  in the herdr pane)
  sync with main (`git merge|rebase|pull ... main`, `gh pr update-branch`)
      while another holds the turn  denied once, with the reason; repeating passes
                                    (whoever needs what already landed on main is
                                    not stuck)
  `squad-turn request [PR] | release | status`   request the turn ahead, give it back, see the queue
The turn is released when the PR shows as MERGED/CLOSED (gh), by
`squad-turn release`, after SQUAD_TURN_IDLE (900 s) with no activity from the
session, after SQUAD_TURN_MAX (3600 s), or after SQUAD_TURN_CLAIM (300 s) if the
session that was called does not show up. Whoever is in the queue is told which
files they have in common with what has just landed.
SQUAD_TURN=0 turns the queue off.

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
TURN_IDLE = env_int("SQUAD_TURN_IDLE", 900)
TURN_MAX = env_int("SQUAD_TURN_MAX", 3600)
TURN_CLAIM = env_int("SQUAD_TURN_CLAIM", 300)
SYNC_PASS = 900        # seconds during which syncing with main, once warned about, passes
AT = r"(?:^|[;&|(\n])\s*"                 # only in command position, not inside text
MERGE_CMD = re.compile(AT + r"(?:gh\s+pr\s+merge\b|git\s+push\b[^|;&\n]*(?:[\s:]|refs/heads/)"
                            r"(?:main|master)\s*(?:$|[|;&\n)]))")
SYNC_CMD = re.compile(AT + r"(?:git\s+(?:merge|rebase|pull)\b[^|;&\n]*\b(?:main|master)\b"
                           r"|gh\s+pr\s+update-branch\b)")
TURN_CLI = re.compile(AT + r"(?:\S*/)?squad-turn(?:\.py)?\s+(request|release|status)\b(?:\s+#?(\d+))?")
PR_NUM = re.compile(r"gh\s+pr\s+merge\s+(?:-\S+\s+)*#?(\d+)")
BRANCH = re.compile(r"[A-Za-z0-9._/-]{1,200}")


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


def turn_kind(p):
    """What the call has to do with the queue: (cli, verb, pr) | (merge, pr) | (sync,) | None."""
    tool = str(p.get("tool_name") or "")
    inp = p.get("tool_input") or {}
    if tool.endswith("merge_pull_request"):
        return ("merge", str(inp.get("pullNumber") or inp.get("pull_number") or ""))
    if tool.endswith("update_pull_request_branch"):
        return ("sync",)
    if tool != "Bash":
        return None
    cmd = str(inp.get("command") or "")
    m = TURN_CLI.search(cmd)
    if m:
        return ("cli", m.group(1), m.group(2) or "")
    if MERGE_CMD.search(cmd):
        m = PR_NUM.search(cmd)
        return ("merge", m.group(1) if m else "")
    if SYNC_CMD.search(cmd):
        return ("sync",)
    return None


def turn_open(repo):
    os.makedirs(TURN, exist_ok=True)
    path = os.path.join(TURN, hashlib.sha1(repo.encode()).hexdigest()[:16] + ".json")
    lock = open(path + ".lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    d = load(path)
    d["repo"] = repo
    d.setdefault("queue", [])
    return path, d, lock


def turn_mark(session, repo=None):
    """Cheap marker that the session is in a queue: avoids opening the queue on every call."""
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


def pr_state(cwd, pr):
    return gh_pr(cwd, pr, "state").upper() if str(pr).isdigit() else ""


def branch_files(repo, branch):
    """Files the branch changes relative to the trunk, by the local refs."""
    if not branch or not BRANCH.fullmatch(branch) or branch.startswith("-"):
        return set()
    for base in ("origin/main", "origin/master"):
        try:
            r = subprocess.run(["git", "--git-dir", repo, "diff", "--name-only", f"{base}...{branch}"],
                               capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            return set()
        if r.returncode == 0:
            return {f for f in r.stdout.splitlines() if f}
    return set()


def common_files(repo, a, b):
    both = sorted(branch_files(repo, a) & branch_files(repo, b)) if a and b and a != b else []
    return (", ".join(both[:8]) + (f" and {len(both) - 8} more" if len(both) > 8 else "")) if both else ""


def turn_entry(p, pr=""):
    cwd = str(p.get("cwd") or "")
    try:
        r = subprocess.run(["git", "-C", cwd, "branch", "--show-current"], capture_output=True, text=True,
                           timeout=5, stdin=subprocess.DEVNULL)
        branch = r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        branch = ""
    now = time.time()
    return {"session": safe(p.get("session_id")), "pr": pr if str(pr).isdigit() else "",
            "branch": branch if BRANCH.fullmatch(branch or "") else "", "cwd": cwd,
            "pane": os.environ.get("HERDR_PANE_ID") or "", "since": now, "seen": now, "asked": now}


def who(e):
    return f"session {e['session'][:8]}" + (f" (PR #{e['pr']})" if e.get("pr") else "") + (
        f", branch {e['branch']}" if e.get("branch") else "")


YOUR_TURN = ("The main branch does not move while the turn is yours. Now, ONCE only and in the card's worktree: `git fetch "
             "origin`, `git merge origin/main`, resolve the conflict if there is one, run the suite, `git push` and "
             "merge the PR. The watcher releases the turn when the PR shows as MERGED; if you give up, `squad-turn release`.")


def turn_wake(e):
    if not (e.get("pane") and os.environ.get("SQUAD_SWITCH") != "0"):
        return
    script = os.path.join(os.path.dirname(os.path.realpath(__file__)), "squad-turn.py")
    try:
        subprocess.Popen([sys.executable, script, "call", e["pane"], e["session"]],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, close_fds=True)
    except OSError:
        pass


def turn_settle(d, me="", force=False):
    """Releases the turn of whoever finished or vanished and calls the next in the queue."""
    now, repo = time.time(), d["repo"]
    for _ in range(len(d["queue"]) + 1):
        h = d.get("holder")
        if h:
            why = ""
            if h.get("pr") and (force or now - h.get("checked", 0) > 20):
                h["checked"] = now
                state = pr_state(h.get("cwd"), h["pr"])
                if state in ("MERGED", "CLOSED"):
                    why = state
            if not why and h.get("called") and h["seen"] <= h["since"] and now - h["since"] > TURN_CLAIM:
                why = "no-show"
            if not why and (now - h["seen"] > TURN_IDLE or now - h["since"] > TURN_MAX):
                why = "idle"
            if not why:
                return
            d["last"] = {"session": h["session"], "pr": h.get("pr"), "branch": h.get("branch"),
                         "at": now, "why": why}
            d["holder"] = None
            if h["session"] != me:
                turn_mark(h["session"])
                if why != "MERGED":
                    turn_note(h["session"], f"[squad-watch] MERGE QUEUE: your turn in {repo} was released "
                              f"({why}). To land the PR, `squad-turn request` again.")
            if why == "MERGED":
                for e in d["queue"]:
                    both = common_files(repo, h.get("branch"), e.get("branch"))
                    if both and e["session"] != me:
                        turn_note(e["session"], f"[squad-watch] MERGE QUEUE: main moved with PR "
                                  f"#{h['pr']}, which touches files of your branch {e['branch']}: {both}. "
                                  "Do not sync yet; on your turn the conflict, if there is one, will be in those.")
        if not d["queue"]:
            return
        e = d["queue"].pop(0)
        e.update(since=now, seen=now, called=True)
        d["holder"] = e
        if e["session"] != me:
            turn_note(e["session"], f"[squad-watch] MERGE TURN: it is your turn in {repo}"
                      + (f" (PR #{e['pr']})" if e.get("pr") else "") + f". {YOUR_TURN} With no activity from you in "
                      f"{TURN_CLAIM // 60} min, the turn passes on.")
            turn_wake(e)
            return


def turn_pre(p, st):
    """Merge queue on PreToolUse. Returns True if it denied the call."""
    kind = turn_kind(p)
    if not kind or os.environ.get("SQUAD_TURN") == "0":
        return False
    repo = git_dir(str(p.get("cwd") or ""))
    if not repo:
        return False
    me = safe(p.get("session_id"))
    path, d, lock = turn_open(repo)
    try:
        turn_settle(d, me)
        h = d.get("holder")
        mine = bool(h and h["session"] == me)
        queued = next((e for e in d["queue"] if e["session"] == me), None)
        pr = kind[-1] if kind[0] in ("cli", "merge") else ""
        if kind[0] == "merge" and not pr and p.get("tool_name") == "Bash":
            pr = gh_pr(str(p.get("cwd") or ""), "", "number")    # without a number MERGED cannot be seen
        denied = ""
        if kind[0] == "sync":
            if h and not mine and time.time() - st.get("sync_ok", 0) > SYNC_PASS:
                st["sync_ok"] = time.time()
                denied = (f"[squad-watch] MERGE QUEUE: main is about to move. The merge turn belongs to {who(h)}"
                          + (f" and there are {len(d['queue'])} in the queue" if d["queue"] else "") + ": syncing now "
                          "tends to be redone, and the conflict resolved today comes back. To land your PR, request "
                          "the turn (`squad-turn request <PR>`) and sync only once, when MERGE TURN arrives. "
                          "If you need what has ALREADY landed on main to continue development, repeat the "
                          "command: this time it passes.")
        elif kind[0] == "cli" and kind[1] == "release":
            if mine:
                d["last"] = {"session": me, "pr": h.get("pr"), "branch": h.get("branch"),
                             "at": time.time(), "why": "released"}
                d["holder"] = None
                turn_settle(d, me)
            d["queue"] = [e for e in d["queue"] if e["session"] != me]
            turn_mark(me)
        elif kind[0] == "cli" and kind[1] == "status":
            pass
        elif mine:
            h["seen"] = time.time()
            if pr:
                h["pr"] = pr
        elif not h and (not d["queue"] or d["queue"][0]["session"] == me):
            d["queue"] = [e for e in d["queue"] if e["session"] != me]
            d["holder"] = turn_entry(p, pr or (queued or {}).get("pr", ""))
            turn_mark(me, repo)
        else:
            if queued:
                queued["pr"] = pr or queued.get("pr", "")
            else:
                queued = turn_entry(p, pr)
                d["queue"].append(queued)
                turn_mark(me, repo)
            if kind[0] == "merge":
                pos = d["queue"].index(queued) + 1
                both = common_files(repo, (h or {}).get("branch"), queued.get("branch"))
                mins = int((time.time() - h["since"]) / 60) if h else 0
                denied = (f"[squad-watch] MERGE QUEUE: the turn in this repository belongs to {who(h)}, for {mins} min now. "
                          if h else "[squad-watch] MERGE QUEUE: there are sessions ahead of you. ")
                denied += (f"You are in the queue, position {pos}. Do not repeat the merge and do NOT sync with "
                           "main now: it will move before your turn. ")
                if both:
                    denied += f"Files in common with the PR that holds the turn: {both}. "
                if p.get("agent_id"):
                    denied += ("Report back to the orchestrator: PR ready, waiting for the merge turn; the merge belongs "
                               "to the main session, when the watcher calls it.")
                else:
                    denied += ("Carry on with another step of the request, or stop saying that the PR is waiting for its turn. The watcher "
                               "announces MERGE TURN in this session" + (" and wakes the pane" if queued.get("pane")
                                                                         else "")
                               + ". On your turn: fetch, merge main ONCE, suite, push, merge.")
        save(path, d)
    finally:
        lock.close()
    if denied:
        deny(denied)
    return bool(denied)


def turn_post(p):
    """After the call: keeps the turn alive, releases it once the PR landed and says what to do."""
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
    out = []
    path, d, lock = turn_open(repo)
    try:
        h = d.get("holder")
        if h and h["session"] == session:
            cmd = str((p.get("tool_input") or {}).get("command") or "")
            if kind or re.search(r"\b(?:git|gh)\s", cmd):     # only merge work keeps the turn alive
                h["seen"] = time.time()
            if kind and kind[0] == "merge":
                turn_settle(d, session, force=True)
                if not d.get("holder") or d["holder"]["session"] != session:
                    turn_mark(session)
                    nxt = d.get("holder")
                    out.append(f"[squad-watch] MERGE QUEUE: PR #{h.get('pr')} landed on main; the turn was "
                               "released" + (f" and passed to {who(nxt)}." if nxt else "."))
                elif not h.get("told"):
                    h["told"] = True
                    out.append(f"[squad-watch] MERGE TURN: the turn in this repository is yours. {YOUR_TURN} If the "
                               "merge has just failed because of a conflict or an out-of-date branch, now is the time "
                               "to sync.")
        elif not any(e["session"] == session for e in d["queue"]):
            turn_mark(session)
        save(path, d)
    finally:
        lock.close()
    return out


# -------------------------------------------------------------------- events
def pre_tool(p):
    agent = p.get("agent_id")
    if turn_kind(p):
        path = state_path(p.get("session_id"), agent)
        st = load(path)
        was = st.get("sync_ok")
        hit = turn_pre(p, st)
        if st.get("sync_ok") != was:
            save(path, st)
        if hit:
            return
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
