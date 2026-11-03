# Pull request bodies

The `pull-request` skill owns the structure: the title rule, the opening
paragraph, the ten required sections in their order, and `pr_check.py`, which
gates them (`~/.claude/skills/pull-request/templates/body.md`). This file keeps
what `writing` owns inside that structure: the readability rules, the
30-second test and the visuals. Read both before drafting a title or body.

A PR body answers five questions:

1. What changes for the system or the user?
2. Why is the change needed?
3. What is the scope, and what was deliberately left out?
4. How was it verified?
5. What is the risk, and how do you roll back?

In the squad, an infrastructure PR states the monthly cost even for an ephemeral
resource, at the full-month ceiling, with the `finops` quote. The project may have
its own rule (PR gate, language, template): the project's rule wins.

## Readability rules

- The outcome goes in the first sentence. Never open with "This PR introduces",
  "This PR aims to" or a generic overview.
- Describe observable changes and decisions, not every file touched.
- Do not narrate the sequence of attempts the agent made.
- Do not repeat commit messages.
- Do not paste full test logs. Give the command, the result, and the decisive
  line.
- Do not claim "tests pass". Name the tests that ran.
- Do not use a long list where a small table allows comparison.
- No more than seven consecutive bullets. Beyond that, group by behaviour or
  split the PR.
- One subject per PR. A second independent subject becomes another branch and
  another PR.
- Say what did **not** change when the diff could suggest a wider scope than the
  real one.
- State breaking changes, migrations, cost, blast radius and rollback when they
  apply.
- Preserve names, commands, tickets, results and values exactly as verified.
- Use a screenshot for a visual change. Diagrams go in the `State and flow`
  section, drawn only from what the diff, plan or IaC contains.
- The title describes the outcome, not the agent's activity. Not "Update files",
  "Various fixes", "Improvements" or "Refactor code". It opens with a verb,
  names what changed and for whom, and is in the repository's language; `pr_check.py` rejects
  branch names, plan vocabulary (`phase 6`, `Wave 1`) and code identifiers.

## The 30-second test

Before opening or updating the PR, confirm a reviewer can answer each of these
without reconstructing the work from a file list, commit log or raw output:

| Question | Where the answer is |
|---|---|
| What is the goal? | Title and opening paragraph |
| What changes? | `Before and after`, `Resources created`, `Resources deleted`, `Functions created and deleted` |
| How was it tested? | `Scans` and `Tests` |
| Is there operational risk? | `Risk analysis` |
| What deserves attention in the diff? | Opening paragraph, or a specific note |

If any answer requires rebuilding the work from raw material, the PR is not ready.

## Visuals in a PR

The medium rules from `visuals.md` apply, at low ceremony:

- a table to compare before/after, environments, permissions, cost or behaviour;
- the `State and flow` diagrams, or `None.` and the reason when nothing has a
  lifecycle or a flow;
- a screenshot or annotated figure for an interface change;
- inside a required table section, the smallest table that holds the facts,
  or `None.` and the reason; never a table padded to look complete;
- no prose restating the whole visual;
- the visual next to the claim it supports.

A PR is not a report or a presentation. When the full explanation runs several
pages, the PR states the decision and links the ADR, RFC, ticket or document that
is the source of truth.
