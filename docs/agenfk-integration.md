# AgenFK integration

[AgenFK](https://github.com/cglab-public/agenfk) is an agentic engineering
framework by CG/lab: a board of cards, a flow of steps with exit criteria, and
gates that are enforced mechanically. In Claude Code it blocks edits when no
card is active, and it advances a card only when evidence is logged against
the current step.

The squad is built on top of that, not next to it. This page says exactly
where the two meet.

## Who owns what

| Concern | AgenFK | Squad |
|---|---|---|
| What the work is | Cards: epics, stories, tasks, bugs | `product` writes them |
| What "done" means for a step | The flow's exit criteria | `flows/squad-delivery.json` names the agent and the evidence |
| Permission to edit | `agenfk gatekeeper` | Every writing agent calls it first |
| Moving a card forward | `agenfk verify --evidence` | Only the main session calls it |
| The record | Comments, test logs, token events | Agents write comments; `finops` reads tokens |
| Who may do which job | (not its concern) | Agents with fixed tool lists |
| Context, fan-out, merge order | (not its concern) | The watcher |

If you take one thing from this page: **AgenFK decides whether a step is
complete; the squad decides who is allowed to claim it.**

## The commands the squad uses

All of these are standard AgenFK CLI commands. The squad adds none.

| Command | Used by | When |
|---|---|---|
| `agenfk create` | `product` | Breaking a goal into cards |
| `agenfk get <id>` / `agenfk list` | every agent | Reading the card before acting |
| `agenfk flow show --project <id> --json` | main session, `verifier` | Loading the steps and their exit criteria |
| `agenfk gatekeeper --item-id <id>` | `developer`, `frontend`, `infra`, `tester` | Before the first edit |
| `agenfk comment <id>` | every agent | Recording a result, a pause, a finding |
| `agenfk log-test <id>` | `tester` | Recording the suite result |
| `agenfk verify <id> --evidence "..."` | **main session only** | Advancing a step |
| `agenfk tokens` | `finops`, `context` | Cost per card, project and model |

The watcher also knows about AgenFK in one place: a sub-session past its
context cut is denied every tool call **except `git` and `agenfk`**, so it can
still commit its work and comment on its card before returning.

## The Squad Delivery flow

[`flows/squad-delivery.json`](../flows/squad-delivery.json) is an AgenFK flow
in the format of the community registry. Its steps line up with the agents.

| Step | Owner | AgenFK command | Evidence `agenfk verify` must carry |
|---|---|---|---|
| **TODO** | `product` (plus `github` for parallel work) | `agenfk create`, `agenfk verify` | Acceptance criteria as written on the card; for parallel work, the worktree path and branch |
| **IMPLEMENT** | `developer`, `frontend` or `infra` | `agenfk gatekeeper --item-id <id>` before editing | Branch, commit SHAs, the suite command and its result, anything left out |
| **TEST** | `tester` | `agenfk gatekeeper`, `agenfk log-test` | Tests added, suite result, and for each new test the mutation that made it fail |
| **REVIEW** | `verifier` | `agenfk comment` with the verdict | `SHIP`/`FIX_FIRST`/`REJECT`, the suite as run by the verifier, findings and their resolution |
| **ADVERSARIAL** | `verifier`, fresh session | `agenfk comment` | Each attack tried and what happened; the verdict |
| **MUTATE** | `verifier` | `agenfk comment` | Mutations applied, killed versus survived, tests added for survivors, a clean tree |
| **VERIFY** | main session | `agenfk verify`, `agenfk tokens` | Criterion-by-criterion table (criterion, command, observed result), PR URL, token cost |
| **DONE** | | | The server runs the project's `verifyCommand` |

On every successful `agenfk verify`, AgenFK returns the **next** step's exit
criteria as work instructions. Because those criteria name the agent, the main
session is told which agent to dispatch next by the board itself, not by its
memory of this document.

### Why the steps are in this order

- **TEST before REVIEW.** The verifier reviews code that already has tests, so
  it can spend its attention on whether the tests prove the right thing.
- **ADVERSARIAL separate from REVIEW.** A review confirms the change does what
  the card says. An adversarial pass tries to make it do something else. Asked
  to do both at once, a reviewer does the first and calls it the second.
- **MUTATE last among the checks.** Mutation is the slowest check and the one
  most worth skipping when the earlier ones already failed.
- **VERIFY by the main session.** The session that advances the card must
  hold the evidence itself. It did not write the code and did not review it;
  it checks that each criterion maps to something that was run.

A shorter flow is fine for a small project. Drop ADVERSARIAL and MUTATE and
the agents still work: `CLAUDE.md` routes any of REVIEW, ADVERSARIAL, MUTATE
and VERIFY to the `verifier` when the active flow has them. With AgenFK's
default flow (`TODO → IN_PROGRESS → REVIEW → TEST → DONE`) `developer` takes
IN_PROGRESS, `verifier` takes REVIEW and `tester` takes TEST.

## Setting it up

### 1. Install AgenFK

Follow the upstream guide:
<https://github.com/cglab-public/agenfk#installation--setup>. When it is done:

```bash
agenfk health          # the framework is up
agenfk --version
```

`install.sh` in this repository warns, and continues, if `agenfk` is not on
your PATH.

### 2. Initialise your project

```bash
cd your-project
agenfk init            # creates .agenfk/project.json
agenfk current-project # prints the project id
```

### 3. Activate the flow

The flow is not in the AgenFK community registry yet (see the
[roadmap](../ROADMAP.md)), so `agenfk flow install` will not find it. Until
then, create it once from the file:

- **Flow Editor (recommended).** Run `agenfk ui`, open the Flow Editor from
  the board's toolbar, create a flow named `Squad Delivery`, and add the steps
  from `flows/squad-delivery.json` in order, pasting each `exitCriteria`.
  Then choose **Set as active**.
- **CLI.** `agenfk flow create "Squad Delivery"` walks you through the same
  steps interactively. Then:

  ```bash
  agenfk flow list                         # find the id
  agenfk flow use <flow-id> --project <project-id>
  ```

Check what the agents will see:

```bash
agenfk flow show --project <project-id> --json
```

Once the flow is published to the registry this becomes one command:
`agenfk flow install squad-delivery.json`.

### 4. Tell AgenFK how to verify

AgenFK runs the project's `verifyCommand` at the final step. Set it to your
real suite. A flow whose last gate runs nothing is a flow that approves
everything.

## Using an existing flow

You do not have to adopt `Squad Delivery`. The squad reads whatever flow the
project has active. The agents match on step **names**:

| Step name in your flow | Agent |
|---|---|
| `TODO` | `product` |
| `IMPLEMENT`, `IN_PROGRESS` | `developer` (or `frontend`, `infra`) |
| `TEST` | `tester` |
| `REVIEW`, `ADVERSARIAL`, `MUTATE`, `VERIFY` | `verifier` |

A step with another name is handled by the main session following that step's
exit criteria, unless your project's `CLAUDE.md` maps it to an agent.

**The project's flow and the project's `CLAUDE.md` take precedence over the
squad.** If your flow's exit criteria say a review may be done by the author
for small changes, that is what happens.

## Precedence, in one list

1. The project's AgenFK flow and its exit criteria.
2. The project's `CLAUDE.md` / `AGENTS.md`.
3. A project agent in `.claude/agents/` with the same role.
4. The squad's `CLAUDE.md` and agents.

## What AgenFK does not see

AgenFK's token events tell you what a card cost. They do not stop a session
while it is spending. That gap is what the watcher fills: it acts during the
session, on numbers read from the transcript, without the server's
involvement. The two records are complementary, and `finops` reads the AgenFK
one while `context` reads the watcher's (`~/.claude/squad/metrics.jsonl`).
