# Modes and document shapes

## Modes

`technical` is the default. Pick a mode explicitly when the user names one,
otherwise infer it from the document type and stay in it. Mode changes tone and
ordering. It never changes which facts appear.

| Mode | Use for | Voice |
|---|---|---|
| `technical` | Specs, ADRs, READMEs, architecture docs, runbooks | Direct, precise, neutral. No persuasion. Trade-offs stated with their cost. First person plural only for team decisions |
| `executive` | Board material, monthly reports, budget and risk notes | Conclusion first, then impact, cost, risk, and the decision being asked for. Numbers in the first paragraph. No implementation detail unless it changes the decision |
| `conversational` | Long messages to colleagues, announcements, onboarding text | Natural and friendly, still professional. Contractions and direct address are fine. No corporate warmth theatre |

## Shapes

Use the shape when the document is one of these types. Do not invent sections.

**README.** What it is (one line). How to run it (commands). Configuration (table
or list). Known limits. No Introduction, no Conclusion.

**ADR / RFC.** Decision in one sentence, first. Context (facts only). Options
considered, one line each with the reason it lost. Consequences. Rollback. The
recommendation is the first line, never the last.

**Runbook.** Preconditions (RBAC, scopes, licences). Steps, numbered, one command
each. Validation: the command that proves it worked. Rollback: the command that
undoes it. A destructive step gets `DESTRUCTIVE` on the line above.

**Postmortem.** Impact (numbers, duration, who). Timeline with timestamps. Root
cause in one sentence. What changes, with an owner and a date. No blame, no
adjectives.

**Message (Slack, WhatsApp, email).** The ask or the decision in the first sentence.
What you need from the reader and by when. Nothing else. No greeting paragraph,
no "hope this helps".

**PR body.** The `pull-request` skill owns the shape: outcome title, plain
opening paragraph, ten fixed sections, checked by its `pr_check.py`. One
subject per PR: if a second subject appeared during the work, it goes to its
own branch off the base branch.

**AgenFK card or issue.** The instruction with the commands, the repository named
and the before and after check. "Push the 4 commits" without naming the repository
cannot be acted on.

**Handoff.** What is done (SHA, branch, card), what is left, the next executable
step and what blocks it. Whoever picks it up reads it in a minute and acts
without asking.

**Executive report.** Conclusion, the number, the risk, the decision requested.
One page. Detail goes in an appendix or a linked artifact.
