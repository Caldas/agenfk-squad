# Swarm supervision in Pi

The bridge loads agents, skills and trusted `.claude/CLAUDE.md` instructions without
rewriting the original resources. Native routing injects up to two suggestions before
an agent run; an explicit `/swarm <agent> <task>` choice is not rerouted. Worktree-local
specialists and skills take precedence. Skills marked `disable-model-invocation`
are not recommended automatically. A suggestion is guidance, not proof of dispatch:
actual delegation appears as a `subagent` tool call.

## Activate and inspect

```sh
bash install.sh --pi
```

In each existing Pi session, wait for its current task to finish, then run:

```text
/reload
/squad-status
```

New sessions load the installed bridge automatically. Existing sessions do not acquire
new handlers until reloaded. Installation does not inject commands into other terminals,
restart their jobs, or change Claude settings. Keep the installed source worktree:
the shim imports it directly. `/claude-compat` lists resources and legacy hook status;
`/squad-status` reports the separate native Pi supervisor, its limits and current state.

## Native controls

- The context window is the selected model's real window, not a fixed one-million-token
  assumption. Default warning: 70%; parent handoff order: 90%. A child receives a return
  instruction at `min(180000 tokens, 80% of its window)`, not a session replacement.
  The cockpit's visual thresholds are independent; its earlier blink is not itself an
  order to stop.
- Active sessions are checked on tool completion and every minute. A handoff order
  enters model context, not just the UI. An ignored order gets at most one final-boundary
  continuation per user run; errors and aborts are not restarted by that reminder.
- Limits: 60 dispatches per session, 4 concurrent children, 6 concurrent Pi orchestrators,
  and 6 review dispatches per card across Pi sessions. Reviews need the card UUID.
  A short atomic reservation coordinates parent processes. Cancellation/completion
  releases its live reservation; dead processes do not consume live slots.
- Five identical calls in the last twelve produce a warning; the eighth is blocked with
  a termination hint. This detects repetition, not semantic lack of progress.
- State survives reload/resume. Denied briefs are preserved privately for a later handoff.
  A denial is not permission to change tools or spawn the same work through Bash.

## Handoff and pickup

After a handoff order, the agent finishes its current step, records the card and calls
`squad_handoff` with a factual summary and an executable next step. The tool records:

- Session, transcript path, worktree, card and latest user request. Requests exceeding
  16,000 characters are explicitly truncated; consult the retained original transcript.
- Verified Git branch, HEAD, porcelain status and a fingerprint covering tracked changes
  and non-ignored untracked file contents across the Git root, even when Pi starts in a
  subdirectory.
- Summary, decisions, next step and the location of preserved denied briefs.

Notes live under `~/.pi/agent/squad/handoffs/`, with private directory/file permissions.
In TUI/RPC, a vigia-ordered handoff queues `/squad-pickup auto:<note-digest>`. The command
waits for successful settlement, checks cancellation, note integrity, current user-message
history, pending tools/messages and Git again. Only then does Pi create a new session,
link the old transcript as its parent and restore the original provider/model, thinking
level and active tool names through the replacement extension. The note is submitted only
after that restoration is acknowledged; missing models/tools stop pickup without fallback.
A changed requirement, changed Git state, failed capture or abort preserves the old session.
A manual note can be resumed with `/squad-pickup`.

Print/JSON one-shot processes save the note and stop; they do not schedule an asynchronous
replacement that their host could dispose before completion. The caller can resume the
saved session and invoke `/squad-pickup` explicitly. Automatic switching is tested through
the real persistent RPC CLI using a local fixture provider, not a paid model request.

## Idle pre-cache compaction

After a successful cache-confirmed request, the native supervisor can compact an idle
TUI/RPC parent before its expected cache expiry. Defaults: at least 150,000 context
tokens and a 120-second lead. It uses `ctx.compact()`, not `/compact` typed into a
terminal, a Claude hook, or a new conversation turn. The transcript and session stay
intact; only the future model context is summarized by Pi.

TTL evidence comes from protocol-level `cache_control`, explicit request retention
(`30m` / `24h`), or the conservative minimum of the model's `promptCache` catalog tiers
when the default `short` tier is known. Long-only metadata and unrecognized explicit
retention do not fall back to a guessed TTL.
Catalog lifetimes are best-effort estimates, not guaranteed discounts. Cache usage must
be reported by the successful response. Unknown TTL/usage, a fallback response model,
or disabled native auto-compaction means no scheduled compaction. Subscription quotas
are never treated as cache expiry. OpenAI/Codex models without validated lifetime
metadata or explicit request retention remain unsupported rather than assuming five minutes.

The timer is bound to the request, session, model, branch leaf and activity generation.
New input (including steering), a tool/shell job, dialog, model/session/branch change,
queued work, handoff or another compaction invalidates it. At dispatch it checks again,
including native settings; a late timer is skipped instead of spending against a cold
cache. Reload cancels the timer and waits for a fresh request. Child sessions and
print/JSON one-shot hosts do not schedule idle compaction.

Native warming takes priority when it already intends to refresh an idle cache. The
supervisor does not change the user's warming setting; it prevents a duplicate warm
request only while its own compaction is running. One native compaction attempt is made
per eligible request, without a supervisor retry loop. Pi may use separate history and
turn-prefix summary calls inside that attempt. Native usage/cost accounting remains intact.

The preservation instruction names the owner's latest request, card, branch/worktree/PR,
decisions, constraints, executed evidence, done/pending work, next step and live jobs.
Summary fidelity is still model-dependent; the original transcript remains the fallback.
`/squad-status` exposes the plan/deadline/source or skip reason. Started/completed/failed
attempts are recorded as `squad-precache-v1` transcript metadata, without request payloads
or credentials. To opt out, set `vigia.preCache.enabled` to `false`; disabling Pi's native
`compaction.enabled` also prevents this automatic feature.

## Configuration and rollback

Only Pi configuration is used. Optional settings in `~/.pi/agent/claude-compat.json`:

```json
{
  "swarmRoot": "/absolute/path/to/installed/swarm-worktree",
  "vigia": {
    "enabled": true,
    "preparePercent": 70,
    "handoffPercent": 90,
    "maxDispatches": 60,
    "maxChildren": 4,
    "maxOrchestrators": 6,
    "maxReviews": 6,
    "autoPickup": true,
    "preCache": {
      "enabled": true,
      "minTokens": 150000,
      "beforeSeconds": 120
    }
  }
}
```

Invalid numeric settings fall back to defaults; concurrency/review caps cannot be raised
above the documented ceilings through this configuration. Set `autoPickup` to `false`
to keep supervision but require manual pickup. Set `enabled` to `false`, then `/reload`,
to disable native supervision. Persistent review counts are in `~/.pi/agent/squad/sessions/reviews/`;
exhaustion requires an owner decision, not an automatic counter reset.

The installer prints a timestamped backup directory. To roll back, restore its
`claude-skills.ts` and `usage-dashboard.ts` into `~/.pi/agent/extensions/`, restore
`claude-compat.json` (or remove the new configuration if none existed before installation),
and `/reload`. Retain both source worktrees until the rollback
window closes. Notes and transcripts are not deleted by rollback.

## Boundaries

Only `subagent` dispatches through the bridge are counted. Direct `pi -p` subprocesses,
external orchestration and detached shell jobs are not tracked as children. Verify such
jobs before handing off. Counts coordinate Pi parents, not Claude/Codex orchestrators.
This is a workflow control, not an OS sandbox or a substitute for trust/permission gates.

The Claude merge queue and herdr terminal automation are not ported.
Pi's built-in safety compaction is unchanged; idle pre-cache compaction uses its native API. No Claude lifecycle hook is enabled by this
module. Source-agent model aliases are not forced; children still inherit the Pi model.
The supervisor never advances cards, merges, deploys or approves its own implementation.
