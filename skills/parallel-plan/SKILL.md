---
name: parallel-plan
description: Propose deterministic dispatch waves from an explicit AgenFK card export, dependencies and touched files. Use before parallelizing an epic, for inherited story dependencies, blocked prerequisites, critical path questions, "what can run in parallel" and "o que pode rodar em paralelo". Read-only forecast; does not dispatch, create cards/worktrees or advance status.
---

# parallel-plan: dependencies first, file collisions second

The failure this prevents: dispatching siblings together while a parent story
still depends on unfinished work, or while both agents will rewrite one file.

## 0. The project decides

Load the project's instructions and flow. `product` defines the smallest
vertical slices and real prerequisites; `github` owns branch/worktree geometry.
This skill gives them a forecast, not a new scheduler agent or dispatch power.
No board, branch or card is modified by the script. Recollect the plan when a
card closes. A forecast never overrides gatekeeper or a human approval step.

## 1. Declare the graph

Use the complete card export, not only active tasks: parents and completed
prerequisites must be present. Each card can carry these lines outside fences:

```text
Depends on: schema-card (consumes its contract)
Touches: src/billing/, docs/*.md, state:payments
Size: 2
```

Comma-separated fields also work as JSON `depends_on`, `touches`, `size`.
The input is a list, `{"items": [...]}` or `{"cards": [...]}`. Each card needs
a unique string `id`; `parentId` is a full id. Dependency prefixes must resolve
uniquely. Fields and description constraints are combined, never discarded.
A completed parent with an unfinished child is inconsistent input, not a way
to mark every child done. Fix the board/export before computing a forecast.
Size is a positive integer, a planning weight, not measured hours.

Parent dependencies and touches constrain **every leaf** below them. Depending
on a container means depending on all its leaves. Cycles, ambiguous/unknown
ids, missing parents and invalid paths are errors, not guessed edges.
Empty containers are leaves: do not dispatch an empty EPIC as code work.

Only DONE/CLOSED satisfy a prerequisite. BLOCKED, PAUSED, CANCELLED, ARCHIVED,
TRASHED and IDEAS (and their inherited constraints) are not completed work;
they and their dependents are reported blocked. Check custom flow semantics
with the owner instead of silently mapping a cancelled item to DONE.

## 2. Compute

```sh
agenfk list --project <id> --json > /tmp/cards.json
python3 -I -B skills/parallel-plan/scripts/waves.py /tmp/cards.json --max-width 4
```

JSON output: `waves`, `ready`, `blocked`, `unknown_touches`, `done`,
`critical_path`, `critical_length`. Exit 0 means a forecast was computed (it
may contain blocked cards); exit 2 means invalid input. No recursive graph
walk, including long chains. Ties sort by full id, independent of export order.
The critical length is a dependency-only weighted lower bound; file conflicts
and reviewer availability can make delivery take longer.

## 3. Check collisions and dispatch boundaries

Same path, directory/pattern overlap or equal `kind:name` resource serializes.
A bare path is conservatively treated as possibly a directory even without a
trailing slash. A trailing `(note)` is not part of Touches; commas inside
parenthesized dependency/path notes do not split entries. Malformed notes fail.
Globs are conservative and can produce false conflicts; narrow Touches only
after inspecting the real file set. Relative paths only, no parent traversal.
No Touches = a singleton wave, **not** evidence that it can run beside others.
Include registries, lockfiles, generated files and shared contracts, not just
primary source files. Resolve uncertainty before dispatching.

`ready` is only the first wave; later waves assume earlier ones completed.
Check which ready cards are already running before assigning a session.
`github` supplies one card/branch/worktree/session per writer, at most four
fronts. Same file means series even across worktrees. The main session alone
dispatches and advances cards; only an independent verifier approves them.

## Origin

New implementation of dependency-wave ideas from the owner's weekly archive
(2026-10-12). No patches were applied wholesale and no new agent role was added.
