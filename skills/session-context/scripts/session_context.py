#!/usr/bin/env python3
"""Context indicators for the AI sessions on this machine: Claude Code, Codex and pi.

Reads the transcripts (read-only, it never writes to them) and prints, per
session: current context and % of the window, weighted burn, reread share,
repeated tool calls (a loop signal), files read again and again (waste), age
of the project's latest handoff, and a verdict: CONTINUE / COMPACT / HANDOFF /
LOOP / IDLE.

    session_context.py                       # sessions active in the last 6h, every client
    session_context.py --all --hours 48      # everything from the last 48h
    session_context.py --cwd /some/path      # only the sessions of that project
    session_context.py --session <id|file> --detail   # one session, with its most reread files
    session_context.py --json                # machine-readable output

Weights and thresholds come from the cockpit (~/.claude/cockpit/statusline.py):
a cache read costs 0.1 of an input token, a cache write 1.25, output 5; HANDOFF
shows at 50% of the window and is urgent at 80%.
"""
import argparse
import glob
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

HOME = os.path.expanduser("~")
W_WRITE, W_READ, W_OUT = 1.25, 0.1, 5.0


def env_num(name, default, lo, hi):
    """Integer from an environment variable, clamped to [lo, hi]. An invalid
    value falls back to the default: a mistyped threshold must not bring down
    the watcher, which fails open."""
    try:
        value = int(os.environ.get(name) or default)
    except ValueError:
        value = default
    return min(max(value, lo), hi)


HANDOFF_SHOW, HANDOFF_NOW = 50, env_num("SQUAD_CTX_PCT", 80, 10, 100)
LOOP_REPEATS = 3          # same tool + same arguments, N times in the last 30 calls
REREAD_FILE = 3           # same file read N+ times
# The reread handoff rule is arithmetic, not a judgement call: the reread share
# (the cockpit's REREAD %) reached REREAD_SHARE AND the context is past the
# floor. Without the floor the rule only measures the session's age: with
# caching, ~30 tool calls already give 50% reread at 10-15% of the window.
REREAD_SHARE = env_num("SQUAD_REREAD", 60, 10, 95) / 100.0          # reread / (new + reread)
REREAD_FLOOR_PCT = env_num("SQUAD_REREAD_FLOOR", 50, 0, 100)        # % of the window below which reread does not trigger
# The floor is not fixed: it weighs the burn. A session with a large context
# and low burn has just built its context and has not used it yet; cutting it
# throws away what it paid to load. The floor starts at HANDOFF_NOW (80%) with
# zero burn and falls in a straight line to REREAD_FLOOR_PCT (50%) when the
# burn reaches BURN_FULL_PCT of the session budget (the cockpit's BURN %).
# Burn 10% -> floor at 74% of the window.
BUDGET = env_num("CLAUDE_SESSION_BUDGET", 20_000_000, 1_000_000, 10**10)
BURN_FULL_PCT = env_num("SQUAD_BURN_FULL", 50, 1, 100)
CTX_BASE = env_num("SQUAD_CTX_BASE", 40_000, 1_000, 500_000)  # context of a new session with the handoff already read
HANDOFF_OUT = 2_000        # output tokens needed to write the handoff
IDLE_MIN = 90             # minutes without activity = idle
DEFAULT_WINDOW = {"claude": 1_000_000, "codex": 258_400, "pi": 128_000}
# Known windows; when the transcript does not state the window, use the
# smallest one that fits the largest context seen in the session (shown as
# "inferred").
KNOWN_WINDOWS = (128_000, 200_000, 258_400, 400_000, 1_000_000, 2_000_000)


def handoff_math(inp, wr, rd, out, ctx, window=0):
    """The handoff arithmetic, in weighted tokens (cockpit weights).

    new       = input + 1.25*cache-write + 5*output    what the session produced
    reread    = 0.1*cache-read                         what it paid to reread itself
    share     = reread / (new + reread)                the cockpit's REREAD %
    ratio     = reread / new                           the same measure on another scale
    toll      = 0.1*ctx                                the toll paid on every new turn
    restart   = 1.25*CTX_BASE + 5*HANDOFF_OUT          writing the handoff and rebuilding the cache
    payback   = restart / (0.1*(ctx - CTX_BASE))       turns until the new session pays for itself
    burn_pct  = (new + reread) / BUDGET                the cockpit's BURN %
    floor_min = max(2*CTX_BASE, REREAD_FLOOR_PCT% of the window)
    floor     = floor_min when burn_pct >= BURN_FULL_PCT; rises in a straight
                line to HANDOFF_NOW% of the window at zero burn
    due       = share >= REREAD_SHARE and ctx >= floor the only reread-based handoff rule

    High reread with a small context is the cache doing its job, not waste:
    that is why it only becomes HANDOFF above the floor. `window` = 0
    (sub-session, unknown window) leaves the floor at 2*CTX_BASE.
    """
    new = inp + wr * W_WRITE + out * W_OUT
    reread = rd * W_READ
    saving = (ctx - CTX_BASE) * W_READ
    restart = CTX_BASE * W_WRITE + HANDOFF_OUT * W_OUT
    share = reread / (new + reread) if new + reread else 0.0
    burn_pct = 100.0 * (new + reread) / BUDGET
    low = min(REREAD_FLOOR_PCT, HANDOFF_NOW)
    floor_pct = HANDOFF_NOW - (HANDOFF_NOW - low) * min(1.0, burn_pct / BURN_FULL_PCT)
    floor_min = max(2 * CTX_BASE, int(window * low / 100))
    floor = max(2 * CTX_BASE, int(window * floor_pct / 100))
    return {"new": int(new), "reread": int(reread), "burn": int(new + reread),
            "burn_pct": round(burn_pct, 1), "ratio": round(reread / new, 3) if new else 0.0,
            "share": round(share, 3), "floor": floor, "floor_min": floor_min,
            "toll": int(ctx * W_READ), "restart": int(restart),
            "payback": round(restart / saving, 1) if saving > 0 else None,
            "due": bool(share >= REREAD_SHARE and ctx >= floor)}


def jsonl(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except Exception:
                    continue
    except OSError:
        return


_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]|\x1b\[[0-9;?]*[ -/]*[@-~]")


def clean(value, limit=200):
    """Everything that comes from a transcript is third-party data: strip
    control characters and ANSI sequences (which could rewrite the terminal or
    hide text) and cap the length. Line breaks become spaces so that a path or
    a name never takes more than one row of the table."""
    s = "" if value is None else str(value)
    s = _CTRL.sub("", s).replace("\n", " ").replace("\r", " ")
    return s[:limit] + ("…" if len(s) > limit else "")


def norm_args(obj):
    # `description` and the like change on every call without changing what it does
    if isinstance(obj, dict):
        obj = {k: v for k, v in obj.items() if k not in ("description", "timeout", "run_in_background")}
    try:
        s = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    except Exception:
        s = str(obj)
    return s[:400]


def blank():
    return {"inp": 0, "wr": 0, "rd": 0, "out": 0, "req": 0, "ctx": 0, "ctx_max": 0,
            "tools": Counter(), "calls": [], "reads": Counter(), "model": "",
            "cwd": "", "started": None, "last": None, "window": None,
            "user_turns": 0}


def set_ctx(st, value):
    st["ctx"] = value
    st["ctx_max"] = max(st["ctx_max"], value)


# ---------------------------------------------------------------- Claude Code
def scan_claude(path, st):
    seen = None
    for d in jsonl(path):
        t = d.get("type")
        ts = d.get("timestamp")
        if ts:
            st["started"] = st["started"] or ts
            st["last"] = ts
        if d.get("cwd") and not st["cwd"]:
            st["cwd"] = d["cwd"]
        if t == "user":
            m = d.get("message") or {}
            c = m.get("content")
            if isinstance(c, str) or (isinstance(c, list) and c and isinstance(c[0], dict) and c[0].get("type") == "text"):
                st["user_turns"] += 1
        if t != "assistant":
            continue
        m = d.get("message") or {}
        st["model"] = m.get("model") or st["model"]
        u = m.get("usage") or {}
        rid = d.get("requestId")
        if u and rid != seen:
            seen = rid
            st["req"] += 1
            st["inp"] += u.get("input_tokens", 0)
            st["wr"] += u.get("cache_creation_input_tokens", 0)
            st["rd"] += u.get("cache_read_input_tokens", 0)
            st["out"] += u.get("output_tokens", 0)
            set_ctx(st, u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                    + u.get("cache_read_input_tokens", 0))
        for b in m.get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                name = b.get("name") or "?"
                inp = b.get("input") or {}
                st["tools"][name] += 1
                st["calls"].append((name, norm_args(inp)))
                if name == "Read" and inp.get("file_path"):
                    st["reads"][inp["file_path"]] += 1
    if "[1m]" in (st["model"] or "") or "1m" in os.environ.get("CLAUDE_CONTEXT_WINDOW", ""):
        st["window"] = 1_000_000


def claude_sessions(hours):
    cutoff = time.time() - hours * 3600
    out = []
    for p in glob.glob(os.path.join(HOME, ".claude", "projects", "*", "*.jsonl")):
        try:
            if os.path.getmtime(p) < cutoff:
                continue
        except OSError:
            continue
        slug = os.path.basename(os.path.dirname(p))
        cwd = "/" + slug.strip("-").replace("-", "/")  # approximate; the slug loses real hyphens
        sid = os.path.basename(p)[:-6]
        out.append(("claude", sid, p, cwd))
    return out


def claude_subsessions(hours):
    """Claude Code sub-sessions (sub-agents): one transcript per agent at
    <project>/<session>/subagents/agent-<id>.jsonl, with the type in .meta.json."""
    cutoff = time.time() - hours * 3600
    out = []
    for p in glob.glob(os.path.join(HOME, ".claude", "projects", "*", "*", "subagents", "agent-*.jsonl")):
        try:
            if os.path.getmtime(p) < cutoff:
                continue
        except OSError:
            continue
        out.append(("claude", os.path.basename(p)[6:-6], p, ""))
    return out


def sub_info(path):
    """(parent session, agent type) when the path belongs to a sub-session."""
    d = os.path.dirname(path)
    if os.path.basename(d) != "subagents":
        return None, None
    kind = ""
    try:
        with open(path[:-6] + ".meta.json", encoding="utf-8") as fh:
            kind = json.load(fh).get("agentType") or ""
    except (OSError, ValueError, AttributeError):
        pass
    return os.path.basename(os.path.dirname(d)), kind


# ---------------------------------------------------------------- Codex
def scan_codex(path, st):
    for d in jsonl(path):
        t = d.get("type")
        p = d.get("payload") or {}
        ts = d.get("timestamp")
        if ts:
            st["started"] = st["started"] or ts
            st["last"] = ts
        if t == "session_meta":
            st["cwd"] = p.get("cwd") or st["cwd"]
        elif t == "turn_context":
            st["model"] = p.get("model") or st["model"]
        elif t == "event_msg" and p.get("type") == "token_count":
            info = p.get("info") or {}
            tot = info.get("total_token_usage") or {}
            last = info.get("last_token_usage") or {}
            st["inp"] = tot.get("input_tokens", 0) - tot.get("cached_input_tokens", 0)
            st["rd"] = tot.get("cached_input_tokens", 0)
            st["wr"] = tot.get("cache_write_input_tokens", 0)
            st["out"] = tot.get("output_tokens", 0)
            set_ctx(st, last.get("input_tokens", 0) + last.get("cache_write_input_tokens", 0))
            st["window"] = info.get("model_context_window") or st["window"]
            st["req"] += 1
        elif t == "response_item":
            kind = p.get("type")
            if kind == "function_call" or kind == "custom_tool_call":
                name = p.get("name") or "?"
                args = p.get("arguments") or p.get("input") or ""
                st["tools"][name] += 1
                st["calls"].append((name, norm_args(args)))
                m = re.search(r'"(?:path|file_path|file)"\s*:\s*"([^"]+)"', str(args))
                if m and name in ("read_file", "read", "view", "cat"):
                    st["reads"][m.group(1)] += 1
            elif kind == "message" and (p.get("role") == "user"):
                st["user_turns"] += 1


def codex_sessions(hours):
    cutoff = time.time() - hours * 3600
    out = []
    for p in glob.glob(os.path.join(HOME, ".codex", "sessions", "*", "*", "*", "rollout-*.jsonl")):
        try:
            if os.path.getmtime(p) < cutoff:
                continue
        except OSError:
            continue
        sid = os.path.basename(p).split("-", 4)[-1][:-6] if "-" in os.path.basename(p) else p
        out.append(("codex", sid, p, ""))
    return out


# ---------------------------------------------------------------- pi
def scan_pi(path, st):
    for d in jsonl(path):
        t = d.get("type")
        ts = d.get("timestamp")
        if ts:
            st["started"] = st["started"] or ts
            st["last"] = ts
        if t == "session":
            st["cwd"] = d.get("cwd") or st["cwd"]
        elif t == "model_change":
            st["model"] = d.get("modelId") or st["model"]
        elif t == "message":
            m = d.get("message") or {}
            role = m.get("role")
            if role == "user":
                st["user_turns"] += 1
            if role != "assistant":
                continue
            u = m.get("usage") or {}
            if u:
                st["req"] += 1
                st["inp"] += u.get("input", 0)
                st["rd"] += u.get("cacheRead", 0)
                st["wr"] += u.get("cacheWrite", 0)
                st["out"] += u.get("output", 0)
                set_ctx(st, u.get("input", 0) + u.get("cacheRead", 0) + u.get("cacheWrite", 0))
            for b in m.get("content") or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") in ("toolCall", "tool_use", "tool_call"):
                    name = b.get("name") or "?"
                    args = b.get("arguments") or b.get("input") or {}
                    st["tools"][name] += 1
                    st["calls"].append((name, norm_args(args)))
                    if name in ("read", "Read") and isinstance(args, dict):
                        fp = args.get("path") or args.get("file_path")
                        if fp:
                            st["reads"][fp] += 1


def pi_sessions(hours):
    cutoff = time.time() - hours * 3600
    out = []
    for p in glob.glob(os.path.join(HOME, ".pi", "agent", "sessions", "*", "*.jsonl")):
        try:
            if os.path.getmtime(p) < cutoff:
                continue
        except OSError:
            continue
        sid = os.path.basename(p).split("_", 1)[-1][:-6]
        out.append(("pi", sid, p, ""))
    return out


# ---------------------------------------------------------------- analysis
def latest_handoff(cwd):
    """Latest handoff OF THE PROJECT: the .claude/handoffs directory at the
    repo root (walking up from the cwd, worktrees included) and, failing that,
    the global ones whose name mentions the project. A global handoff from
    another project never counts."""
    cands = []
    probe = os.path.abspath(cwd) if cwd else ""
    names = set()
    while probe and probe != "/":
        names.add(os.path.basename(probe).lower())
        cands += glob.glob(os.path.join(probe, ".claude", "handoffs", "*.md"))
        if os.path.isdir(os.path.join(probe, ".git")) or os.path.isfile(os.path.join(probe, ".git")):
            break
        probe = os.path.dirname(probe)
    if not cands and names:
        for p in glob.glob(os.path.join(HOME, ".claude", "handoffs", "*.md")):
            base = os.path.basename(p).lower()
            if any(n and len(n) > 3 and n.replace("_", "-") in base for n in names):
                cands.append(p)
    if not cands:
        return None, None
    best = max(cands, key=os.path.getmtime)
    return best, (time.time() - os.path.getmtime(best)) / 60


def loops(calls):
    tail = calls[-30:]
    c = Counter(tail)
    rep = [(k, n) for k, n in c.items() if n >= LOOP_REPEATS]
    streak, best = 1, 1
    for i in range(1, len(tail)):
        streak = streak + 1 if tail[i] == tail[i - 1] else 1
        best = max(best, streak)
    return rep, best


def analyse(client, sid, path, cwd_hint, now):
    st = blank()
    {"claude": scan_claude, "codex": scan_codex, "pi": scan_pi}[client](path, st)
    if not st["req"]:
        return None
    st["cwd"] = st["cwd"] or cwd_hint
    window, inferred = st["window"], False
    if not window or st["ctx_max"] > window:
        inferred = True
        window = next((w for w in KNOWN_WINDOWS if w >= st["ctx_max"]), KNOWN_WINDOWS[-1])
        if client == "claude":
            window = max(window, DEFAULT_WINDOW["claude"])
    c = handoff_math(st["inp"], st["wr"], st["rd"], st["out"], st["ctx"], window)
    burn, reread_share = c["burn"], c["share"]
    ctx_pct = 100.0 * st["ctx"] / window if window else 0.0
    rep, streak = loops(st["calls"])
    reread_files = [(f, n) for f, n in st["reads"].most_common() if n >= REREAD_FILE]
    try:
        idle_min = (now - os.path.getmtime(path)) / 60
    except OSError:
        idle_min = None
    ho_path, ho_age = latest_handoff(st["cwd"])

    verdict, why = "CONTINUE", []
    if idle_min is not None and idle_min > IDLE_MIN:
        verdict = "IDLE"; why.append(f"no activity for {idle_min:.0f} min")
    if rep or streak >= LOOP_REPEATS:
        verdict = "LOOP"; why.append(f"call repeated {max([n for _, n in rep] + [streak])}x")
    if ctx_pct >= HANDOFF_NOW:
        verdict = "HANDOFF"; why.append(f"context {ctx_pct:.0f}% >= {HANDOFF_NOW}%")
    elif ctx_pct >= HANDOFF_SHOW and verdict == "CONTINUE":
        verdict = "COMPACT"; why.append(f"context {ctx_pct:.0f}% >= {HANDOFF_SHOW}%")
    if c["due"]:
        if verdict in ("CONTINUE", "COMPACT"):
            verdict = "HANDOFF"
        why.append(f"reread {c['share']:.0%} (>= {REREAD_SHARE:.0%}) with context above the floor of "
                   f"{human(c['floor'])}; every turn rereads "
                   f"{human(c['toll'])}; a new session pays for itself in {c['payback']:g} turn(s)")
    if reread_files and verdict == "CONTINUE":
        why.append(f"{len(reread_files)} file(s) read {REREAD_FILE}+ times")
    if ho_age is not None and ctx_pct >= HANDOFF_SHOW and ho_age > 240:
        why.append(f"last handoff {ho_age/60:.0f}h ago")

    reread_files = [(clean(f), n) for f, n in reread_files]
    rep = [((clean(k[0], 60), k[1]), n) for k, n in rep]
    parent, agent_type = sub_info(path) if client == "claude" else (None, None)
    return {
        "parent": clean(parent, 80) if parent else None, "agent_type": clean(agent_type, 60),
        "client": client, "session": clean(sid, 80), "path": path, "cwd": clean(st["cwd"]),
        "model": clean(st["model"], 80), "requests": st["req"], "user_turns": st["user_turns"],
        "ctx_tokens": st["ctx"], "window": window, "window_inferred": inferred,
        "ctx_pct": round(ctx_pct, 1),
        "burn_weighted": int(burn), "reread_share": round(reread_share, 3),
        "reread_ratio": c["ratio"], "turn_toll": c["toll"], "restart_cost": c["restart"],
        "payback_turns": c["payback"],
        "out_tokens": st["out"], "tool_calls": sum(st["tools"].values()),
        "top_tools": [(clean(k, 60), n) for k, n in st["tools"].most_common(5)],
        "repeated_calls": [(k[0], n) for k, n in rep], "max_streak": streak,
        "reread_files": reread_files[:8],
        "idle_min": None if idle_min is None else round(idle_min),
        "handoff": clean(ho_path), "handoff_age_min": None if ho_age is None else round(ho_age),
        "verdict": verdict, "why": why,
    }


def human(n):
    n = float(n or 0)
    for unit, div in (("M", 1e6), ("k", 1e3)):
        if n >= div:
            return f"{n/div:.1f}{unit}"
    return f"{n:.0f}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hours", type=float, default=6)
    ap.add_argument("--all", action="store_true", help="include idle sessions")
    ap.add_argument("--cwd", help="only sessions whose cwd starts with this path")
    ap.add_argument("--client", choices=["claude", "codex", "pi"])
    ap.add_argument("--session", help="id or path of one session")
    ap.add_argument("--detail", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--subs", action="store_true", help="include sub-sessions (Claude Code sub-agents)")
    ap.add_argument("--watch", type=int, metavar="SEC",
                    help="repeat every SEC seconds and print only the sessions whose verdict changed")
    ap.add_argument("--tasks", action="store_true",
                    help="metrics per finished sub-session, from the squad-watch log")
    a = ap.parse_args()

    if a.tasks:
        return tasks(a.hours)
    if a.watch:
        return watch(a)
    rows = collect(a)
    return report(rows, a)


def collect(a):
    now = time.time()
    found = claude_sessions(a.hours) + codex_sessions(a.hours) + pi_sessions(a.hours)
    if a.subs or a.session:
        found += claude_subsessions(a.hours)
    if a.session:
        found = [f for f in found if a.session in f[1] or a.session == f[2]]
        if not found and os.path.isfile(a.session):
            c = "claude" if "/.claude/" in a.session else "codex" if "/.codex/" in a.session else "pi"
            found = [(c, os.path.basename(a.session), a.session, "")]
    rows = []
    for client, sid, path, cwd in found:
        if a.client and client != a.client:
            continue
        r = analyse(client, sid, path, cwd, now)
        if not r:
            continue
        if a.cwd and not (r["cwd"] or "").startswith(os.path.abspath(a.cwd)):
            continue
        if not a.all and r["verdict"] == "IDLE" and not a.session:
            continue
        rows.append(r)
    rows.sort(key=lambda r: (-r["ctx_pct"], -r["burn_weighted"]))
    return rows


def watch(a):
    """Sentinel: it neither decides nor acts; it only reports when a session
    changes verdict. One line per change, to run in a pane or under Monitor."""
    a.subs = True
    seen = {}
    while True:
        for r in collect(a):
            key = (r["client"], r["session"])
            if seen.get(key) == r["verdict"]:
                continue
            first = key not in seen
            seen[key] = r["verdict"]
            if r["verdict"] == "CONTINUE" and first:
                continue
            who = f"sub {r['agent_type'] or '?'} of {r['parent'][:8]}" if r["parent"] else r["client"]
            print(f"{time.strftime('%H:%M:%S')} {r['verdict']:9} {who} {r['session'][:8]} "
                  f"ctx {r['ctx_pct']:.0f}% burn {human(r['burn_weighted'])} reread {r['reread_share']:.0%} "
                  f"{(r['cwd'] or '?').replace(HOME, '~')} — {'; '.join(r['why']) or 'back to normal'}",
                  flush=True)
        time.sleep(max(a.watch, 15))


LOG = os.path.join(HOME, ".claude", "squad", "metrics.jsonl")


def tasks(hours):
    """Reads the log the squad-watch hook writes at the end of every sub-session."""
    cutoff = time.time() - hours * 3600
    rows = [d for d in jsonl(LOG) if isinstance(d, dict) and d.get("ts", 0) >= cutoff]
    if not rows:
        print(f"no sub-session recorded in the last {hours:g}h ({LOG.replace(HOME, '~')})")
        return 0
    by = defaultdict(lambda: {"n": 0, "burn": 0, "calls": 0, "loop": 0, "cut": 0, "ctx": 0.0})
    for d in rows:
        b = by[clean(d.get("agent_type") or "?", 30)]
        b["n"] += 1
        b["burn"] += d.get("burn", 0) or 0
        b["calls"] += d.get("calls", 0) or 0
        b["loop"] += 1 if d.get("loop_warned") else 0
        b["cut"] += 1 if d.get("cut") else 0
        b["ctx"] = max(b["ctx"], d.get("ctx_pct", 0) or 0)
    print(f"{'agent':18} {'sub-sessions':>12} {'burn':>8} {'burn/sub':>8} {'calls':>6} {'ctx/peak':>8} {'loop':>4} {'cuts':>6}")
    for k, b in sorted(by.items(), key=lambda kv: -kv[1]["burn"]):
        print(f"{k:18} {b['n']:>12} {human(b['burn']):>8} {human(b['burn'] / b['n']):>8} "
              f"{b['calls']:>6} {b['ctx']:>7.0f}% {b['loop']:>4} {b['cut']:>6}")
    return 0


def report(rows, a):
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    if not rows:
        print("no session in the selection")
        return 0
    print(f"{'verdict':9} {'cli':6} {'ctx':>12} {'burn':>7} {'reread':>6} {'r/new':>6} {'pback':>5} {'calls':>5} {'loop':>4} {'idle':>5}  session / project   (~ = window inferred from the largest context seen)")
    for r in rows:
        ctx = f"{human(r['ctx_tokens'])}/{human(r['window'])}{'~' if r['window_inferred'] else ''}"
        proj = (r["cwd"] or "?").replace(HOME, "~")
        print(f"{r['verdict']:9} {r['client']:6} {ctx:>12} {human(r['burn_weighted']):>7} "
              f"{r['reread_share']:>6.0%} {r['reread_ratio']:>6.0%} "
              f"{(format(r['payback_turns'], 'g') + 't') if r['payback_turns'] else '-':>5} "
              f"{r['tool_calls']:>5} {r['max_streak']:>4} "
              f"{(str(r['idle_min'])+'m') if r['idle_min'] is not None else '?':>5}  "
              f"{r['session'][:8]} {proj}"
              + (f"  [sub {r['agent_type'] or '?'} of {r['parent'][:8]}]" if r["parent"] else ""))
        if r["why"]:
            print(f"{'':9} reason: " + "; ".join(r["why"]))
        if a.detail:
            print(f"{'':9} model {r['model'] or '?'} · {r['requests']} req · {r['user_turns']} prompts · "
                  f"output {human(r['out_tokens'])} · tools {r['top_tools']}")
            for f, n in r["reread_files"]:
                print(f"{'':9} reread {n}x  {f.replace(HOME, '~')}")
            for name, n in r["repeated_calls"]:
                print(f"{'':9} repeated {n}x  {name}")
            if r["handoff"]:
                print(f"{'':9} handoff {r['handoff_age_min']} min ago  {r['handoff'].replace(HOME, '~')}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.exit(0)
