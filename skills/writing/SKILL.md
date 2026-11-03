---
name: writing
description: The squad's method to write, edit, audit, calibrate and compress text a person (or an agent) will read, in English or pt-BR, without reading as AI and without losing a fact: doc, README, ADR, spec, report, runbook, PR body, commit message, AgenFK card, handoff, email, Slack or WhatsApp post, interface microcopy, code comment, chat reply. Fidelity over readability, voice over polish, uncertainty is a fact; lean mode for chat (caveman), slop linter, fidelity check, compressing CLAUDE.md/AGENTS.md/memory behind a fidelity gate, brand voice read from the project, choosing between prose, table and diagram, an HTML document that wears the project's design system. Use before writing, even one line, and on "review this", "does this read as AI", "make it sound human", "write like me", "lean mode", "caveman", "fewer tokens", "be brief", "compress CLAUDE.md", "commit message", "proofread", "tighten this", "revise isto", "isso parece IA?", "escreve como eu", "mensagem de commit".
---

# writing: the reader has five minutes; every sentence pays for its share

The failure this method prevents: text that says little with many words, in
the rhythm every model produces (an opening that announces, a body in three
items, a closing that repeats), and that along the way changes a number, drops
a "maybe" or invents a source. The second failure is the rewrite that leaves
the text smooth and strips out the writer's voice.

## 0. The project decides

Before writing for a project, read `CLAUDE.md` / `AGENTS.md` and look for the
project's own skills in `.claude/skills/`. **The project's rules and skills
beat this one**: PR template and gate, commit convention, declared language,
voice guide, the design system for the look. This skill is the default for
when the project has none. Language, register and voice come from the project
(section 10), never from a fixed project or person.

Who uses it: every squad agent that writes text for a person (landing page,
card, handoff, PR, report, commit, README). The skill writes; sending,
publishing and posting always belong to the owner. `$WRITING` is this skill's
directory (`~/.claude/skills/writing`); the scripts are Python stdlib, run them
with `python3 -I`.

## 1. Five jobs: pick one before you start

| Job | Trigger | Output |
|---|---|---|
| **Write** (default) | You produce the text: doc, message, PR, reply | The text, nothing about the text |
| **Edit** | The owner hands over a draft to fix | The edited draft and a short `What changed` |
| **Detect** | "does this read as AI?", "audit this", "point it out without rewriting" | Named patterns, one quoted line for each, the fix in a few words. No rewrite, no score, no claim about who wrote it |
| **Calibrate** | Two or more samples: "write like me", "the product's voice" | A voice profile in the format of `references/voice-profile.md`, to edit and keep |
| **Compress** | "compress CLAUDE.md", "trim the memory", "fewer tokens in this handoff" | The smaller file with every fact, and the result of `fidelity_check.py` |

In Detect, a named pattern is evidence the owner can check; an AI detector
guesses. A voice profile holds for every later job in the session, goes to the
linter as `--profile` and changes only the mechanical patterns, never a fact
or a banned construction.

## 2. Tiers of ceremony

The process follows the risk. Every tier obeys the rules; only the gate
changes.

| Tier | Text | Process |
|---|---|---|
| 0 | Chat reply, terminal status, commit message, code comment, one-line card | The memory rules. No script, no report, no meta-commentary |
| 1 | PR body, AgenFK card, handoff, Slack or WhatsApp post, email, changelog, short README | The rules plus the mechanical sweep (section 9) |
| 2 | More than ~400 words a third party reads: spec, ADR, proposal, report, postmortem, architecture doc | The full process; both scripts pass before you say done |

**Lean mode.** On "lean mode", "caveman", "be brief" or "fewer tokens", tier 0
gets stricter until "normal mode": answer first, zero ceremony, articles
optional and negation never, one idea per sentence of up to 20 words, payload
(code, command, path, error) verbatim, tool status kept short, no performing
the mode. Drop back to full sentences for a security warning, an irreversible
action, an order of steps, a confused requester, a question to the user, and
everything that is recorded outside the chat. A **commit message** follows the
repository's convention (read `git log` first); with no convention,
Conventional Commits in the imperative, body with the why only. Full rules and
the check before sending: `references/lean.md`.

Tier 0 is not an exemption: the rules apply to every reply in the session,
because after a few turns the default cadence comes back. Memory self-check
for tiers 0 and 1: the last block of `eval.md`.

## 3. Severity

Findings do not weigh the same, and the order decides what gets fixed first
and what never ships. Structure weighs more than lexicon: a document with a
clean word list and an announce-body-summary shape is still slop, and a
precise term that is on the list is not.

| Level | What | Gate |
|---|---|---|
| Blocks | An invented fact, name, number, date, quote or source. A qualifier dropped, weakened or strengthened. A decision, number or requirement changed. Code, table, link or frontmatter touched. A contradiction with the source | Never ships. No `allow` directive covers it. `fidelity_check.py` non-zero, or an item of the coverage list missing |
| Fix | A linter ERROR: banned lexicon or construction, generic heading, emoji, list instead of prose, chatbot residue. Structural: empty opening, summarising closing, paragraphs from the same mould | Fix it, or keep it with a one-line justification or an inline `allow`. Never by deleting the fact the finding sits in |
| Prefer to fix | A linter WARN: soft constructions, rhythm, density, transitions, certainty, nominalization, portability | Fix it when it costs no fact. Otherwise leave it and move on |
| Advisory | An `eval.md` judgement: the 15% cut, headings, medium, symmetry | Your call. Say what you left |

## 4. The three rules above everything

**Fidelity beats readability.** Never change a requirement, decision, number,
name, risk, acceptance criterion or fact to make the sentence flow. If the
fact reads badly, change the sentence around it, not the fact. Never invent a
fact, name, number, date, quote or source. Keep verbatim: code, commands,
diagrams, links, tables, frontmatter, technical identifiers.

**Voice beats polish.** Make the minimum edit that solves it. First note the
draft's vocabulary, cadence, bluntness, humour, uncertainty and digressions,
and keep them. Do not leave every paragraph equally tidy; a strong opinion, a
swear word and an honest admission stay when they belong to the writer.
Opening up a text is not dumbing it down. Personality fits a post and an
opinion piece; reference, legal and incident text stay neutral.

**Uncertainty is a fact.** "May", "estimated", "inferred" and "not measured
yet" say how much the writer knows. Cutting stacked hedges leaves one hedge
and names what is uncertain; it never promotes the claim. In security, legal,
financial, medical and incident text the qualifier is the content and stays
even when the sentence reads better without it. The reverse is just as wrong:
never hedge a fact the source states.

## 5. The sentence test

Every sentence delivers information, reasoning, necessary context or an
action. A sentence whose only role is emphasis, ceremony or padding: **delete
it, do not rewrite it**.

In technical and operational documents the bar is higher, because the
reasoning there is usually short: every sentence carries a fact, number,
command, name, decision or risk. Executive prose and conversation get room for
cause and framing, and losing that is a different failure.

**Portability test.** If the sentence moves unchanged to another person,
company, country or product, it is padding. Cut it, or replace it with a fact,
mechanism, consequence or judgement specific to the subject.

**Show, do not tell.** Facts, actions and consequences carry the emphasis. Cut
the comment that labels a point as important, surprising or subtle instead of
showing it.

**Put the measure in.** A measurable adjective without a number is a claim
without evidence. A technical classification is not: `public endpoint`,
`private subnet`, `external dependency`, `manual approval`, `reversible
migration` and `immutable tag` are the precise term and stay.

<!-- vale off -->

| Word | Replace with |
|---|---|
| robust / robusto | what it withstands: retry, failover, tested at N |
| scalable / escalável | up to how much: RPS, nodes, GB, tenants |
| significant / significativo | the number |
| fast / rápido | the latency or the duration |
| many / vários | the count |
| recently / recentemente | the date |
| best practice / boa prática | whose, which document |

<!-- vale on -->

## 6. Structure

1. Answer first. The decision, the fix, the number or the command is the
   first line.
2. No opening paragraph announcing what the document covers, no closing
   paragraph repeating it. Each conclusion once; the reader has just read it.
3. A heading names the content ("Rollback"), never asks a question, and is
   never repeated by the first sentence under it. Banned forms: Overview, Key
   takeaways, Final thoughts, Conclusion, Introduction, The road ahead,
   Comprehensive overview, Strategic highlights, Implementation journey.
4. A paragraph carries reasoning. A list is for what really is a set. A table
   only when the reader compares rows against columns.
5. Vary the length of sentences and paragraphs. Never build a group of three
   because three sounds complete.
6. If it fits in three lines, it is three lines.

The message that goes with a file says in one line what changed, with no
"here is the document" and no offer to help. Shapes per document type:
`references/shapes.md`.

## 7. The clearest medium

Do not start with prose by default. Before a long section, name the relation
the reader needs to understand and choose the smallest medium that keeps the
meaning. Full rules in `references/visuals.md`.

| The reader needs to | Use |
|---|---|
| Compare 3+ items on 2+ attributes, or read an exact mapping | Table |
| Follow a sequence, topology, hierarchy, ownership, state or dependency | Diagram |
| Recognise a screen, position, layout, or a before/after | Annotated figure |
| Run a procedure | Numbered steps and code ready to paste |
| Understand cause, nuance or why something was decided | Prose |

A visual comes only from material confirmed in the source, with a one-line
conclusion and alt text, without duplicating it in prose. A generated image
never serves for exact topology, data, values or architecture. A large, empty
diagram is slop.

An architecture or cloud diagram is a claim about a real system: follow the
`cloud-diagram` skill (inventory before geometry, current or proposed, an
editable source, a render probe). This skill takes care only of the prose
around it.

**Rendered document** (HTML, Artifact, its PDF): the look belongs to the
project. Start from `templates/document.html` and replace the `--ds-*` block
at the top with the output of `python3 -I
~/.claude/skills/design-reference/scripts/sweep.py <root> --css` (with no
design system in the project, the squad's neutral palette stays). One
language by default; bilingual only with a bilingual audience or on request,
from `templates/document-bilingual.html` with `<html data-languages="en pt">`.
Before delivering: `python3 -I "$WRITING/scripts/artifact_check.py" <file>`.
PR, card, commit and markdown in `docs/` take none of this. Rules:
`references/rendered-document.md`.

**Presentation**: when a presentation skill is installed, call it **before**
planning the slides; it owns structure, layout and rendering, this skill owns
the prose and the fidelity. Do not turn a README, ADR, runbook, card or email
into slides unless asked.

**Pull request**: the body serves a reviewer with 30 seconds to decide whether
to open the diff: what changes, why, what was left out, how it was verified,
risk and rollback. No narrating the agent's work and no repeating the commits.
Structure: the `pull-request` skill (or the project's); the 30-second test in
`references/pull-requests.md`. Only `github` opens a PR, after the
`verifier`'s SHIP.

## 8. Patterns and words to cut

The catalogue with fixes, the before/after pairs and the word lists in both
languages are in `references/patterns.md` (a quick summary opens the file).
Read it once per session. The most frequent: binary contrast ("it's not just
X, it's Y"), colon revelation, throat-clearing ("it's worth noting"), faux
insight, announcing ("let's dive in"), shallow -ing clause at the end,
puffery, vague source, metadiscourse, hidden actor, clipped negation at the
end ("no drama"), chatbot residue, stacked hedges, a row of dramatic
fragments.

<!-- vale off -->

A flagged word (leverage, seamless, delve, robust; alavancar, robusto,
jornada, ecossistema) gets **deleted**, not swapped for a synonym. Some are
the precise word in context ("strategic decision" in a strategy document;
`gate`, `harness`, `pipeline`, `realm` as technical terms): keeping it costs a
one-line justification or `<!-- writing: allow <term> -->`, never silence. An
empty adverb (just, actually, simply; só, literalmente, na verdade) goes when
it adds nothing and stays when it carries emphasis, uncertainty or the
writer's rhythm.

<!-- vale on -->

## 9. Mechanical sweep

In the final text, from tier 1 up: no em dash or en dash (unless the writer's
sample uses them), straight quotes, sentence-case headings, lower case after a
colon, no emoji, bold only for a defined term or a warning, no list of bold
labels, a code block for everything that gets pasted. Full list in
`references/process.md`.

## 10. Language

Talk to the user in the user's language. The artifact's language follows the
first row that matches:

| Situation | Language |
|---|---|
| The owner asked for a language | The one asked for |
| The artifact already exists | The language it is in |
| The repository declares a policy (`CLAUDE.md` / `AGENTS.md`, or the language of the latest PR titles and commit messages) | The repository's |
| Nothing above decides | English |

When two rows genuinely compete, ask once.

Technical terms, product names, resource types and cmdlets stay in English in
both languages: conditional access, blast radius, drift, `Set-MgUser`, AKS.
Never translate an error message, a log line, a documentation title, or an
existing artifact as a side effect of editing it.

## 11. Process

Each job has a different gate, because the evidence available is different.
Step by step for each one, the fix loop and the full sweep:
`references/process.md`.

| Job | Gate |
|---|---|
| Write | The coverage list (facts, requirements, decisions, risks from the sources) checked item by item against the text, plus the linter. `fidelity_check.py` without an original proves nothing |
| Edit | A copy of the original before touching it; `slop_lint.py` and `fidelity_check.py` exit 0; `eval.md` read against the result |
| Detect | Nothing changes in the artifact. Named pattern, quoted line, short fix; audited evidence in separate buckets (measured, estimated, verified), empty is not zero, cause only against a control, "Not proven" kept apart |
| Calibrate | A profile derived only from the samples, one quoted line per observation. A product voice comes from the project's brand guide and published copy |
| Compress | Prose only; the original outside the tree; `fidelity_check.py` exits 0 (REVIEW checked sentence by sentence) |

```bash
ORIG=$(mktemp); cp <doc> "$ORIG"        # before touching the document
python3 -I "$WRITING/scripts/slop_lint.py" <doc>
python3 -I "$WRITING/scripts/fidelity_check.py" "$ORIG" <doc>
```

A non-zero exit blocks delivery, the way a red test blocks a merge. REVIEW
(negation, modality, polarity) is not a verdict: read both sentences and only
then rerun with `--accept-semantic` if the change was intended; "you should
run" → "run" passes, "never do" → "do" does not. A finding kept on purpose
gets one line in the reply or `<!-- writing: allow <term> -->`; never silence
a finding by deleting the fact it sits in.

**Fix loop:** lint; rewrite only the sentences with findings; lint again until
zero ERROR with every WARN justified; fidelity last, on the final text. Never
regenerate the whole draft: the second pass brings a second set of tics and
loses the voice. The scripts are detectors, not proof; the final semantic pass
is yours, and weighty text (proposal, external report, PR) goes through the
`verifier` before it leaves.

## 12. Non-goals

The target is edited human prose, not simulated imperfection, and prose only.
Never insert fake errors, anecdotes, experiences or slang to "sound human";
never claim the text is undetectable or optimise against a detector; never
force a register or swap the writer's voice for a generic one; never ban a
word globally (`allow` exists); never edit code, JSON, YAML, TOML, a lockfile,
a generated file, a log, shell output or a hash (in a mixed file only the
prose changes, the rest stays byte for byte identical); never send, publish or
post on the owner's behalf.

## 13. References and scripts

| File | What for |
|---|---|
| `references/patterns.md` | Quick summary and the full catalogue, before/after in both languages |
| `references/false-positives.md` | What **not** to flag; read it before every Detect and before editing someone else's voice |
| `references/process.md` | Step by step for each job, the fix loop, the full mechanical sweep |
| `references/lean.md` | Chat lean mode, commit message, Compress |
| `references/voice-profile.md` | Voice profile format, the project's brand voice, microcopy |
| `references/shapes.md` | Document shapes: README, ADR, runbook, postmortem, message, card, handoff, executive |
| `references/visuals.md` | When a table, diagram or figure beats prose, and accessibility |
| `references/pull-requests.md` | The 30-second test for a PR body |
| `references/rendered-document.md` | The project's design system, template, language, export, check |
| `references/checks.md` | What each script detects and its false positive |
| `eval.md` | Self-check before returning an edit |
| `templates/document*.html` | Starting pages with the `--ds-*` block; they pass the check as they are |
| `scripts/slop_lint.py`, `scripts/fidelity_check.py` | Prose gates |
| `scripts/artifact_check.py` | Rendered HTML gate, including the `--ds-*` contract |
| `scripts/selftest.sh` | Proves the gates catch what they claim; `tests/test_writing.py` runs it |
| `hooks/writing-artifact.py` | Artifact hook (contract in the quickstart, check before publishing); registering it is the owner's decision |

## Origin

Adapted from a pack of writing skills: the original visual identity was
removed, the language follows the squad's rule, the language toggle became
optional and the channel examples moved to Slack, WhatsApp, email, README,
AgenFK card and handoff. The pattern catalogue and the false-positive
discipline come from `humanizer` (MIT), based on Wikipedia's [Signs of AI
writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing); voice
preservation, the portability test and the Detect job come from `no-ai-slop`
(petergyang, MIT); lean mode, commit, Compress and the evidence discipline come
from `caveman` (Apache-2.0); the idea of the brand-voice axes from claudekit
`brand` (no licence claimed, own words). The cloud diagram rules moved to
`cloud-diagram`. Licences and attributions in `THIRD_PARTY_NOTICES.md`.
