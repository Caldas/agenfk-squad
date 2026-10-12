# Concepts

Five principles hold the squad together. Each one answers a failure that was
observed, not imagined, and each one is enforced somewhere you can point to: a
tool list, an AgenFK gate, or a line in a hook. A principle that lives only in
a prompt is a wish.

## Where the numbers come from

In one week of October 2026, on one machine running five projects with
Claude Code and AgenFK:

- the orchestrating sessions carried **420k to 966k tokens of context**;
- they spawned **249 sub-agents**, which accounted for **64% of all token
  consumption**;
- **five projects** were orchestrating at the same time overnight;
- one card was sent to review **five times**.

That is a sample of one. It is still enough to show the shape of the problem:
every step taken by those sessions was locally reasonable. The limits below
are the smallest set that would have changed the totals.

## 1. One card = one branch = one worktree = one session

A card is the unit of work, and it owns exactly one of each of the other three.

- **One branch**, so a review judges one change.
- **One worktree**, so two agents never edit the same checkout. An agent that
  finds unexpected changes in its tree cannot tell a colleague's work from its
  own mistake.
- **One session**, so the context holds one problem. A card that does not fit
  in about 120k tokens of context is too big, and goes back to `product` to be
  split.

Parallel work is allowed only across **disjoint files**. Before two or more
agents are dispatched in the same repository, the `github` agent delivers the
map (session → worktree → branch → card) and the table of fronts. The same
file in two fronts means the fronts run in series. The ceiling is about four
fronts: beyond that, the cost of integration grows faster than the work gets
done.

*Enforced by:* `agenfk gatekeeper --item-id <id>` before the first edit; the
`github` agent's writer claim per worktree; the `parallel-git` skill.

## 2. Whoever writes does not approve

A session that wrote a change is the worst judge of whether it is correct. It
carries the reasoning that produced the bug, and it will follow that reasoning
to the same conclusion a second time.

So review is done by a different agent, in a **clean context**, briefed with
the card id and the branch and nothing else. The implementer's account of what
it did is exactly what the reviewer must not read: it is the hypothesis under
test.

The `verifier` has no `Edit` or `Write` tool. It cannot fix what it finds,
which removes the temptation to approve its own fix. It returns one of three
verdicts:

| Verdict | Meaning |
|---|---|
| `SHIP` | The acceptance criteria hold, checked by running something |
| `FIX_FIRST` | Specific defects, each tied to a file and line; back to the implementer |
| `REJECT` | The approach is wrong; back to the implementer or to `product` |

`FIX_FIRST` and `REJECT` loop at most **two rounds**. After that, the decision
is the owner's. Without the cap, a reviewer and an implementer will trade
findings for as long as the budget lasts, which is how one card came to be
reviewed five times.

The `tester` applies the same idea to tests: a test that has never been seen
to fail proves nothing, so each new test is shown red by mutating the code it
targets.

*Enforced by:* the `tools:` line of `agents/verifier.md`; the reviewer cap in
the watcher (`SQUAD_MAX_REVIEWS`, a seventh reviewer on the same card is
denied); the REVIEW, ADVERSARIAL and MUTATE steps of the flow.

## 3. Context is a budget

Every turn of a session re-reads its whole context. With prompt caching that
re-read is cheap per token, about a tenth of the price of fresh input, but it
is paid on every turn and it grows with everything the session has ever seen.
At 600k tokens of context, each turn costs 60k weighted tokens before the
model has produced a word.

Two consequences:

- **A long session should end before it is full**, and hand the work to a
  fresh one. The handoff is a file, written from ground truth (git state plus
  the open request), short enough that reading it costs less than the context
  it replaces.
- **The session does not get to decide when.** Models are poor at estimating
  their own context. Left alone they stop at 30% "to be safe" or run to the
  wall. The watcher measures the transcript and does the arithmetic; the rule
  for the session is to act on the order and otherwise keep working.

The arithmetic is deliberately not just "stop at N%". A session that loaded a
large context and has barely used it should not be cut: it has paid to load
and has not yet earned it back. So the threshold weighs how much the session
has already burned. The numbers are in [watcher.md](watcher.md#the-handoff-arithmetic).

The same budget applies to orchestration. Sub-agents are the largest single
cost (64% in the sample week), so there is a cap on sub-sessions per session,
on sessions orchestrating at once, and on the context of an orchestrator that
wants to dispatch.

*Enforced by:* `hooks/squad-watch.py` on `PostToolUse`, `PreToolUse` and `Stop`.

## 4. Every refusal comes with a way forward

A hook that only denies teaches the model to route around it. Deny an `Agent`
call with "too many sub-agents" and the session will try `Task`, then a shell
loop, then a different agent type. That is not malice; it is a capable system
with a goal and no instruction.

So each denial in this project names the next action:

| Refused | Why | Where the work goes |
|---|---|---|
| Dispatch | Orchestrator past its context ceiling, or 40 sub-sessions used | Write a handoff holding the plan of the denied dispatch and stop; a fresh session executes it |
| Dispatch (implementation) | No orchestrator slot, session is light | Implement the card right here, without an agent |
| Dispatch (implementation) | No orchestrator slot, session is heavy | Handoff with the implementation plan; the fresh session implements directly |
| Dispatch (review) | No orchestrator slot | Carry on with what does not depend on the verdict; wait for `SLOT FREE` |
| Dispatch (review) | Seventh reviewer on one card | Comment on the card, take the decision to the owner |
| Merge | Another session holds the turn | Join the queue; do other work; act on `MERGE TURN` |
| Sync with main | Another session holds the turn | Denied once with the reason; a second attempt goes through |

The stop is also **soft**. The orchestrator is warned before the ceiling
(`DISPATCH NOTICE`), only the *new* dispatch is denied, and the task in
progress finishes. The brief of every denied dispatch is saved in full, so the
plan is not lost with the refusal.

*Enforced by:* the denial texts in `squad-watch.py`, and by tests that assert
each denial names its exit.

## 5. Measured evidence, not narrative

A step is done when something was run and the result is on the card. "I
implemented the feature and all tests pass" is a claim. The command, the
count and the exit code are evidence.

- AgenFK advances a card only with `agenfk verify <id> --evidence "..."`.
- Only the **main session** advances a card, using what the agents returned.
  No squad agent merges, applies, deploys, sends a message or publishes.
- The watcher prints only what it measured: context, weighted burn, reread
  share, turns to pay back a restart. It makes no judgement the reader cannot
  recompute.
- Finance and cost agents quote with a source, a date and a formula, at the
  measured volume and at ten times it.

The same rule governs this repository. A watcher rule is proposed with the
session behaviour that motivated it, and ships with a test.

*Enforced by:* the AgenFK flow; rule 5 of `CLAUDE.md`; the review checklist in
[CONTRIBUTING.md](../CONTRIBUTING.md).

## What the squad is not

- **Not a replacement for AgenFK.** It has no board, no flow engine and no
  gates of its own. Remove AgenFK and the agents lose the card that scopes
  them and the evidence trail that makes their output checkable.
- **Not an autonomous pipeline.** The owner decides what ships. Agents stop at
  `plan`, at a draft, at a verdict.
- **Not tuned for your machine.** The defaults assume a 1M-token window and a
  20M weighted-token budget per session. Read
  [configuration.md](configuration.md) before trusting them.
