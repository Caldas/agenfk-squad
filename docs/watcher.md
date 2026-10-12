# The watcher

`hooks/squad-watch.py` is one Python file, standard library only, registered on
five Claude Code hook events. It reads the transcript of every session and
sub-session, does a fixed piece of arithmetic, and acts. It never crashes a
session: any error ends silently with exit code 0 and a line in
`~/.claude/squad/watch-errors.log`.

Everything it prints starts with `[squad-watch]` and contains only what it
measured. `SQUAD_WATCH=0` turns it off.

- [What runs when](#what-runs-when)
- [The handoff arithmetic](#the-handoff-arithmetic)
- [Sub-sessions: loops and cuts](#sub-sessions-loops-and-cuts)
- [The dispatch brake](#the-dispatch-brake)
- [The soft stop](#the-soft-stop)
- [The session switch](#the-session-switch)
- [The merge queue](#the-merge-queue)
- [Metrics](#metrics)

## What runs when

| Hook event | What the watcher does |
|---|---|
| `PostToolUse` | Records the call and warns on repetition. Every 60 seconds it reads what was appended to the transcript and redoes the arithmetic: context, burn, reread share, payback. A sub-session at its threshold is told to return its handoff; a main session is told to write one. |
| `PreToolUse` | In a sub-session: denies an identical repeated call (loop) and, above the context cut, denies everything except `git` and `agenfk`. In a main session: applies the dispatch brake to `Agent`/`Task` calls and the merge queue to merge and sync commands. |
| `SubagentStop` | Writes the sub-session's metrics to `metrics.jsonl` and leaves a note for the parent when the sub-session ended badly. |
| `UserPromptSubmit` | Delivers pending notes to the main session. |
| `Stop` | Main session at handoff level: if it stopped without writing the handoff, the stop is blocked and the order repeated; if it stops again without one, the watcher writes a minimal handoff itself. With a handoff on disk and nothing running in the background, it launches the session switch. |

Reading the transcript is incremental: the watcher keeps a byte offset per
session and parses only whole lines added since the last look, so it costs the
same on a 5 MB transcript as on a 50 MB one.

## The handoff arithmetic

The watcher weighs tokens the way the API bills them, relative to one fresh
input token:

| Token kind | Weight |
|---|---|
| Input | 1 |
| Cache write | 1.25 |
| Cache read | 0.1 |
| Output | 5 |

From a session's running totals it computes (`handoff_math` in
`skills/session-context/scripts/session_context.py`):

| Name | Formula | Meaning |
|---|---|---|
| `new` | input + 1.25 × cache-write + 5 × output | What the session produced |
| `reread` | 0.1 × cache-read | What it paid to re-read itself |
| `share` | reread / (new + reread) | The reread share |
| `burn` | new + reread | Weighted tokens spent so far |
| `burn_pct` | burn / `CLAUDE_SESSION_BUDGET` | Share of the session budget (default 20M) |
| `toll` | 0.1 × context | What every further turn costs before it does anything |
| `restart` | 1.25 × `SQUAD_CTX_BASE` + 5 × 2,000 | Writing the handoff and rebuilding the cache in a fresh session |
| `payback` | restart / (0.1 × (context − `SQUAD_CTX_BASE`)) | Turns until a fresh session has paid for itself |
| `floor` | see below | The context below which a high reread share is not acted on |
| `due` | share ≥ `SQUAD_REREAD` and context ≥ floor | The reread rule fired |

### The rule

A main session is ordered to hand off (`PROACTIVE HANDOFF`) when either holds:

1. **context ≥ `SQUAD_CTX_PCT`% of the window** (default 80%), or
2. **reread share ≥ `SQUAD_REREAD`%** (default 60%) **and context ≥ floor**.

Rule 1 is the wall. Rule 2 is the interesting one.

### Why there is a floor, and why it moves

A high reread share with a small context is the cache doing its job, not
waste. So rule 2 only applies above a floor.

A fixed floor is still wrong. Picture a session that has just loaded 500k
tokens of context and done almost nothing with it. Its reread share is high
(it has produced little, so most of its spend is re-reading), and its context
is at 50% of the window. Cutting it now throws away what it just paid to load.

So the floor **weighs the burn**. With `window` the session's context window:

```
floor_pct = 80 − (80 − 50) × min(1, burn_pct / 50)
floor     = max(2 × SQUAD_CTX_BASE, window × floor_pct / 100)
```

where 80 is `SQUAD_CTX_PCT`, the lower 50 is `SQUAD_REREAD_FLOOR` and the
divisor 50 is `SQUAD_BURN_FULL`. In words: the floor starts at 80% of the
window for a session that has burned nothing, and falls in a straight line to
50% once the session has burned half its budget.

For a 1M window and a 20M budget:

| Burn so far | `burn_pct` | Floor |
|---|---|---|
| 0 | 0% | 800k (80%) |
| 2M | 10% | 740k (74%) |
| 5M | 25% | 650k (65%) |
| 8M | 40% | 560k (56%) |
| 10M or more | ≥ 50% | 500k (50%) |

### Worked examples

**A. Just loaded, barely used.** Context 500k, burn 2M (10%), reread share 70%.
Floor is 740k. Context is below the floor, so rule 2 does not fire. Rule 1
does not fire either (500k < 800k). The session keeps working. It gets at most
an informational notice, which is not an order to stop.

**B. Same context, long session.** Context 500k, burn 11M (55%), reread share 68%.
Floor is 500k. Context ≥ floor and share ≥ 60%: `PROACTIVE HANDOFF`. Each
further turn costs a toll of 50k weighted tokens. A restart costs
1.25 × 40k + 10k = 60k, and saves 0.1 × (500k − 40k) = 46k per turn, so the
fresh session pays for itself in 60 / 46 ≈ 1.3 turns.

**C. Productive session, low reread.** Context 620k, burn 12M, reread share 41%.
Share is under 60%, so rule 2 does not fire. Context is under 800k, so rule 1
does not fire. The session continues, even though it is large: it is still
producing more than it re-reads.

**D. The wall.** Context 810k, any burn, any share. Rule 1: `PROACTIVE HANDOFF`.

The cut therefore always falls between 50% and 80% of the window. Above 50%
without the arithmetic closing, the session receives only an informational
notice.

Sub-sessions have no known window (`window = 0`), so their floor is
2 × `SQUAD_CTX_BASE` and they are governed by the absolute thresholds below.

### What the session must do

On `PROACTIVE HANDOFF` the session closes the step in progress, comments on
the card, writes the handoff through MODE A of the `clear-pickup` skill
**without asking for permission**, puts what is left of the request under
`## Next step`, and stops. It does not open a new front.

The reverse matters as much: a session must **not** write a handoff or stop
"because the context is high" without a `PROACTIVE HANDOFF`, a
`DISPATCH DENIED`, or a request from the owner. The decision is the watcher's
arithmetic, not the session's estimate. A handoff written without one of those
is flagged as `Handoff out of turn`.

## Sub-sessions: loops and cuts

| Signal | Threshold | Action |
|---|---|---|
| Same call (tool + arguments), in the last 30 calls | 3 times | Warning |
| Same call, in the last 30 calls | 5th time | Denied |
| Same call, back to back | 3 in a row | The next one is denied |
| Context | `SQUAD_SUB_CTX_WARN` (120k) | Told to wrap up and return its handoff |
| Context | `SQUAD_SUB_CTX_CUT` (180k) | Every call denied except `git` and `agenfk` |
| Weighted burn | `SQUAD_SUB_BURN` (2M) | Told to return its handoff |

Fields that change without changing the call (`description`, `timeout`,
`run_in_background`) are ignored when comparing calls.

A sub-session that is cut returns a **return handoff** of at most twelve
lines: DONE (commits and files, with evidence), MISSING, NEXT STEP, BLOCKER.
If its role writes code, it first runs `git add -u` and a `wip:` commit on the
card's branch, so nothing it did is lost. New untracked files are left out of
that commit on purpose and named under MISSING.

The parent then follows one rule: **do not redispatch the same brief.** Read
the return handoff, check in git what actually got done, and dispatch only
what is missing, with a short brief, in a new sub-session. One redispatch.

## The dispatch brake

Before any `Agent` or `Task` call from a main session, the watcher checks four
ceilings:

| Ceiling | Variable | Default |
|---|---|---|
| Context of the orchestrator | `SQUAD_CTX_CEILING` | 600,000 |
| Sub-sessions spawned by this session | `SQUAD_MAX_SUBS` | 40 |
| Sessions orchestrating at the same time | `SQUAD_MAX_ORCH` | 3 |
| Reviewer dispatches for the same card | `SQUAD_MAX_REVIEWS` | 6 (the 7th is denied) |

A session counts as orchestrating while it has a sub-session with activity in
the last ten minutes. A dispatch counts as a reviewer when the agent type or
description matches review, verify, security, audit or adversarial; the card
is recognised by its id in the brief.

A `DISPATCH DENIED` always says where the work continues. There are four exits:

| Situation | Exit | What the session does |
|---|---|---|
| Context ceiling, or sub-session ceiling | **Handoff with the plan** | Writes a handoff whose `## Next step` holds the plan of the denied dispatch (card, branch, worktree, files, steps, acceptance criteria, suite command) and stops. The session switch is armed; the pickup executes the plan. |
| No orchestrator slot, implementation, context < `SQUAD_ORCH_HERE` (120k) | **Do it right here** | Implements the card in the main session, without an agent and without a handoff. This is the one authorised exception to the dispatch rule. The review still belongs to the `verifier`. |
| No orchestrator slot, implementation, context ≥ `SQUAD_ORCH_HERE` | **Handoff with the plan** | As above; the fresh session, with a clean context, implements directly. |
| No orchestrator slot, reviewer | **Wait for the slot** | Carries on with whatever does not depend on the verdict. The watcher sends `SLOT FREE` when a slot opens. The session never approves its own code. |
| Seventh reviewer on the same card | **Owner's decision** | Comments on the card with what keeps failing and takes it to the owner. |

The session must not work around a denial with another tool or another agent
type, and must not repeat the dispatch.

## The soft stop

Nothing is interrupted mid-task.

- Before a ceiling is reached, the orchestrator receives a `DISPATCH NOTICE`.
  It is informational, not an order to stop.
- Only the **new** dispatch is denied. Sub-sessions already running finish,
  and so does the step the main session is in.
- The brief of each denied dispatch is saved in full in
  `~/.claude/squad/handoffs/<session>-dispatches.md`. The handoff points to
  that file instead of retyping the plan.
- If a session at handoff level stops without writing a handoff, the stop is
  blocked and the order repeated. If it stops again without one, the
  watcher writes a minimal handoff on its own, from what it can verify: git
  state, the owner's last request, the denied dispatches.

If the alert no longer applies (the context dropped after a compaction, for
example) the watcher says so with `ALERT CANCELLED`.

## The session switch

When a main session stops at handoff level, with a handoff written **by that
session after the alert**, and nothing running in the background, the watcher
launches `hooks/squad-switch.py` as a detached process:

1. it waits for the agent in the pane to go idle;
2. it checks the pane still hosts the **same** session. If the owner switched
   sessions or is typing something else, it gives up;
3. it sends `/clear` and checks that the pane's session changed;
4. it sends `/clear-pickup pickup <copy>`, where `<copy>` is a read-only copy
   of the handoff, checked by SHA-256. Never "the most recent file in the
   folder", and never the original, which could change after the check.

The fresh session's pickup verifies the handoff against the repository and
continues from `## Next step`. The work carries on without the owner present.

Each step is logged in `~/.claude/squad/switches.log`. Any doubt means giving
up: the handoff is already on disk and the owner can switch by hand with
`/clear` followed by `/clear-pickup pickup`.

The switch needs a pane it can type into, which today means the session runs
inside **herdr** (`HERDR_PANE_ID` is set). Outside herdr the watcher still
orders the handoff, and the session tells the owner the two commands.
`SQUAD_SWITCH=0` disables only the switch.

## The merge queue

With several sessions landing PRs at the same time, each merge moves the main
branch under the others, and the conflict a session just resolved comes back.
The queue makes landing on main one at a time, per repository. State lives in
`~/.claude/squad/turn/`. `SQUAD_TURN=0` disables it.

**Merging** (`gh pr merge`, a direct push to `main` or `master`, the
`merge_pull_request` tool):

| The turn is | Result |
|---|---|
| Free, or already yours | Goes through, and the turn stays with your session |
| Another session's | Denied. Your session joins the queue and is called when its turn comes: `MERGE TURN`, as a note in the session and a prompt in its herdr pane |

**Syncing with main** (`git merge|rebase|pull ... main`, `gh pr update-branch`)
while another session holds the turn is denied **once**, with the reason: main
is about to move, and a conflict resolved now will have to be resolved again.
Repeating the command within fifteen minutes goes through, because a session
that needs something already landed must not be stuck.

**The command**, linked into `~/.local/bin` by the installer:

```bash
squad-turn request [PR]   # ask for the turn, or join the queue
squad-turn release        # give the turn back, or leave the queue
squad-turn status         # who holds the turn, the queue, whether your branch
                          # conflicts with main, files in common with those ahead
```

The first `gh pr merge` requests the turn by itself.

**When `MERGE TURN` arrives:** `git fetch`, `git merge origin/main` **once**,
run the suite, push, merge.

**The turn is released** when the PR shows as MERGED or CLOSED (checked with
`gh`), by `squad-turn release`, after `SQUAD_TURN_IDLE` (900 s) without
activity from the holding session, after `SQUAD_TURN_MAX` (3600 s) in any
case, or after `SQUAD_TURN_CLAIM` (300 s) if a session that was called does
not show up. Sessions in the queue are told which files they have in common
with what just landed.

## Metrics

Every finished sub-session appends one JSON line to
`~/.claude/squad/metrics.jsonl`: agent type, context, weighted burn, calls,
reread share, duration, and how it ended. Read them with:

```bash
python3 skills/session-context/scripts/session_context.py --tasks
```

These numbers are how the thresholds in this file were chosen. If yours
suggest different ones, that is exactly the issue we want to read.
