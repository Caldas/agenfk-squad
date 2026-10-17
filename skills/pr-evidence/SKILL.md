---
name: pr-evidence
description: Check repository PR-template headings and current independent review evidence before opening, revising or declaring a PR ready. Use for "review this PR", "respond to review", "is this ready to merge", stale approvals or CI checks, and "revisa o PR". Does not post comments, approve, resolve threads, wake sessions or merge.
---

# pr-evidence: a review is evidence for one head, not forever

The failure this prevents: a green badge from an old commit, a self-review
mistaken for approval, or a repository template silently omitted by a CLI.

## 0. The project decides

Read the project's instructions, PR template, flow and required checks first.
Its PR-format gate takes precedence. Preserve its language; English is not a
reason to rewrite an existing Portuguese PR. No new mandatory mutation gate.
The owner's instruction authorizes publishing only within the requested scope.

## 1. Write

Read the diff. Use an outcome title, not a branch, phase or card label. Collect
the actual commands and results before drafting. Use the repository template,
including its headings, and run its own title/body gate. Do not invent a verb
allowlist that rejects a valid title merely because a word is new.

```sh
python3 -I -B skills/pr-evidence/scripts/pr_evidence.py template \
  --template .github/PULL_REQUEST_TEMPLATE.md --body /tmp/pr-body.md
```

The script checks headings outside comments and code fences, and nonempty
answers. It is not a semantic prose or title judge. Specify the actual template
when the repo offers multiple templates. If a writing skill is installed, it
reviews prose separately. Nonempty placeholders/unchecked checklist items can
pass this structural check: a human/verifier must assess whether they answer
the question. This is not proof that a check-box task was completed.

## 2. Review, respond, re-review

1. Give the independent reviewer the card, branch and acceptance criteria, not
   the author's narrative. Confirm reviewer identity and authority from the
   repository policy/API, not from a hidden marker in a PR comment.
2. Review correctness, blast radius, security, and the risk of applying versus
   not applying. Verify findings against file:line and a reproducer. A minor
   naming/style preference is a comment, not a veto. A real break or exposure
   blocks. A self-review is useful but is not independent approval.
3. Draft inline comments and show them to the owner before posting. The same
   confirmation applies to the owner's own PR. No automatic session wakeups.
4. The author replies with a fix commit or a reasoned disagreement and leaves
   threads open. Re-review the new head and the changed code, not just replies.
5. Two fix/re-review rounds at most; unresolved disagreement goes to the owner.
   Resolve threads only after reviewer acceptance of the current head and the
   owner's authorization. Never manufacture a reviewer verdict.

## 3. Check current evidence

Read [references/snapshot.md](references/snapshot.md) before collecting data.

```sh
python3 -I -B skills/pr-evidence/scripts/pr_evidence.py review /tmp/review.json \
  --reviewer designated-peer --check suite
```

Exit 0 = READY; 1 = BLOCKED; 2 = WAITING; 3 = invalid input. READY does not
merge or authorize a person to merge. It only describes the supplied snapshot.
Recollect after every push. Unknown threads, missing checks, stale approvals,
and skipped required checks do not count as green. The designated reviewer
cannot be the author. Review/check names are exact, repeat flags when needed.

## 4. Handoff

`github` drafts/opens the PR after the independent verifier's SHIP and the flow's
permission. `verifier` returns findings and evidence; the main session advances
the card. Supply head, verdict, commands, unresolved findings, round and next
owner. The script writes only stdout; it does not contact GitHub.

## Origin

New implementation of reusable review ideas from the owner's weekly tooling
archive (2026-10-12). No corporate templates, automation or configuration copied.
