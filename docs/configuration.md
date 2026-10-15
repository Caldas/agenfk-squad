# Configuration

Every threshold is an environment variable read by the hooks at the moment
they run. Set them where Claude Code will inherit them: your shell profile, or
the `env` block of `~/.claude/settings.json`:

```json
{
  "env": {
    "SQUAD_MAX_ORCH": "2",
    "SQUAD_WINDOW": "200000"
  }
}
```

Values are integers. A value that does not parse falls back to the default,
so a typo does not switch the watcher off. The percentages (`SQUAD_CTX_PCT`,
`SQUAD_REREAD`, `SQUAD_REREAD_FLOOR`, `SQUAD_BURN_FULL`), `SQUAD_CTX_BASE` and
`CLAUDE_SESSION_BUDGET` are also clamped to a sane range. The other ceilings
are taken as given: `SQUAD_MAX_REVIEWS=0` denies every reviewer.

**Start here if your setup differs from the defaults:**

- Your model has a **200k window**, not 1M → set `SQUAD_WINDOW=200000` and
  lower `SQUAD_CTX_CEILING` to match (for example `150000`).
- You do **not use herdr** → nothing to set; the automatic switch simply does
  not run, and the session tells you the two commands to type.
- You want the **measurements without the enforcement** → there is no
  observe-only mode yet. Run `session_context.py --watch 60` in a terminal and
  leave the hooks unregistered.

## Switches

| Variable | Default | Effect |
|---|---|---|
| `SQUAD_WATCH` | on | `0` disables the watcher entirely (all five events) |
| `SQUAD_SWITCH` | on | `0` disables only the automatic session switch; handoffs are still ordered |
| `SQUAD_TURN` | on | `0` disables only the merge queue |

## Main session: when to hand off

See [watcher.md](watcher.md#the-handoff-arithmetic) for the arithmetic.

| Variable | Default | Meaning |
|---|---|---|
| `SQUAD_WINDOW` | 1,000,000 | Context window of the main session, in tokens. When unset, the watcher uses 1M, or a larger value if a status line recorded one in `~/.claude/cache/session-tokens/<session>.json` |
| `SQUAD_CTX_PCT` | 80 | Percent of the window at which the handoff is ordered regardless of anything else. Clamped to 10–100 |
| `SQUAD_REREAD` | 60 | Reread share, in percent, at which the reread rule can fire. Clamped to 10–95 |
| `SQUAD_REREAD_FLOOR` | 50 | Percent of the window that is the lowest the floor can go |
| `SQUAD_BURN_FULL` | 50 | Percent of the session budget at which the floor reaches its lowest point |
| `CLAUDE_SESSION_BUDGET` | 20,000,000 | Weighted tokens one session is expected to spend. `burn_pct` is measured against it |
| `SQUAD_CTX_BASE` | 40,000 | Context of a fresh session that has just read a handoff. Used for the payback and for the minimum floor (2 × this) |
| `SQUAD_CTX_WARN` | 0 (off) | Absolute context, in tokens, for an informational notice |
| `SQUAD_CTX_HANDOFF` | 0 (off) | Absolute context, in tokens, that orders a handoff. Off by default; the percentage rules apply |

## Sub-sessions

| Variable | Default | Meaning |
|---|---|---|
| `SQUAD_SUB_CTX_WARN` | 120,000 | Context at which a sub-session is told to wrap up and return its handoff |
| `SQUAD_SUB_CTX_CUT` | 180,000 | Context above which every call is denied except `git` and `agenfk` |
| `SQUAD_SUB_BURN` | 2,000,000 | Weighted burn at which a sub-session is told to return its handoff |

The loop thresholds are constants in `squad-watch.py`, not variables: a
warning at the 3rd identical call in the last 30, a denial at the 5th, and a
denial after 3 identical calls in a row.

## The dispatch brake

| Variable | Default | Meaning |
|---|---|---|
| `SQUAD_CTX_CEILING` | 600,000 | Orchestrator context above which a new dispatch is denied and a handoff ordered |
| `SQUAD_MAX_SUBS` | 40 | Sub-sessions one main session may spawn |
| `SQUAD_MAX_ORCH` | 3 | Sessions that may orchestrate sub-agents at the same time, across the machine |
| `SQUAD_ORCH_HERE` | 120,000 | With no orchestrator slot: below this context the card is implemented in the session itself; at or above it, handoff with the plan |
| `SQUAD_MAX_REVIEWS` | 6 | Reviewer dispatches allowed for the same card. The next one is denied |

## The merge queue

| Variable | Default | Meaning |
|---|---|---|
| `SQUAD_TURN_HOLD` | 120 | Seconds a merge call may hold the turn; a turn held longer expires (the call never came back) |
| `SQUAD_TURN` | unset | `0` turns off the turn, the conflict check and the seal |
| `SQUAD_SEAL` | unset | `1` turns the merge seal on, `0` off; unset, `git config squad.seal` decides |
| `SQUAD_GH` | `gh` | The GitHub CLI binary used to read a PR's state |

Per repository, with `git config`:

| Setting | Default | Meaning |
|---|---|---|
| `squad.seal` | `false` | `true`: a PR merge or a push to the trunk passes only if the SHA has a SHIP seal (`squad-seal record`) |
| `squad.trunk` | unset | Comma-separated branches that also count as the trunk, besides main, master and the remote's default branch |

`SQUAD_TURN_IDLE`, `SQUAD_TURN_MAX` and `SQUAD_TURN_CLAIM` were removed: the turn now covers only the merge call itself.

## The session switch

| Variable | Default | Meaning |
|---|---|---|
| `HERDR_PANE_ID` | set by herdr | The pane the session runs in. Without it there is no automatic switch |
| `HERDR_BIN_PATH` | `herdr` | The herdr binary |
| `SQUAD_SWITCH_PROMPT` | `/clear-pickup pickup` | The command sent to the fresh session. Exists for testing |

## The session report

`skills/session-context/scripts/session_context.py` reads the same variables
as the watcher, so its report and the watcher's decisions agree. It also reads:

| Variable | Default | Meaning |
|---|---|---|
| `CLAUDE_CONTEXT_WINDOW` | unset | Overrides the window assumed for Claude Code sessions in the report |

Default windows assumed per client when nothing else is known: Claude Code
1,000,000; Codex 258,400; pi 128,000.

```bash
session_context.py                       # sessions active in the last 6 hours, all clients
session_context.py --all --hours 48      # everything from the last 48 hours
session_context.py --cwd /path/to/repo   # only sessions of that project
session_context.py --session <id|file> --detail   # one session, with its most re-read files
session_context.py --tasks               # sub-session metrics from metrics.jsonl
session_context.py --watch 60            # refresh every 60 seconds
session_context.py --json                # machine-readable
```

Each session gets a verdict: `CONTINUE`, `COMPACT`, `HANDOFF`, `LOOP` or `IDLE`.

## Choosing your own numbers

The defaults were tuned on one machine with a 1M window. Before changing them,
look at your own data:

```bash
python3 skills/session-context/scripts/session_context.py --all --hours 168
python3 skills/session-context/scripts/session_context.py --tasks
```

Things worth checking:

- **Where do your sessions actually end?** If most stop at 300k on their own,
  the handoff rule never fires and the defaults are irrelevant to you.
- **What share of your spend is sub-sessions?** If it is small, the dispatch
  brake is not your problem.
- **How many reviewer dispatches does a card get?** If the answer is often
  more than three, lower `SQUAD_MAX_REVIEWS` and look at why reviews do not
  converge.

If your numbers suggest different defaults, open an issue with them. That is
the most useful report this project can receive.
