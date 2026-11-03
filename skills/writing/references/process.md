# Process per job, fix loop and mechanical sweep

Detail of the "Process" and "Mechanical sweep" sections of `SKILL.md`.
`$WRITING` is the skill's directory.

## Process

Each job has a different gate, because the evidence available is different.

**Write** (there is no original). Identify the audience, purpose, language and
requested format; if the audience or format is unclear, ask once. A rendered
document for a project: run the design-system sweep first (`sweep.py --css`,
from `design-reference`). Extract the facts, requirements, decisions, risks
and constraints from the sources into a short coverage list. Choose the medium
for each part. Write without inventing anything. Run the linter on the prose
and then check the coverage list against the text, item by item: that is the
fidelity gate for new content. `fidelity_check.py` against an empty or
unrelated file compares nothing, and a clean result there means nothing.

**Edit** (there is an original). Keep a copy of the original for the diff.
Mark the regions that stay byte for byte identical. Restructure, then rewrite
the prose. Never change the main format without asking, nor the look of a
rendered document. At tier 2:

```bash
ORIG=$(mktemp); cp <doc> "$ORIG"        # before touching the document
python3 -I "$WRITING/scripts/slop_lint.py" <doc>
python3 -I "$WRITING/scripts/fidelity_check.py" "$ORIG" <doc>
```

`slop_lint.py` exits non-zero on any ERROR. `fidelity_check.py` exits non-zero
when a token disappeared (information you removed), appeared (information you
invented), or on a REVIEW line where negation, modality or polarity vocabulary
changed. A non-zero exit blocks delivery, the way a red test blocks a merge.
REVIEW is not a verdict: read both sentences, and only then rerun with
`--accept-semantic` if the change was intended.

Fix what the linter found, or declare it. A finding kept on purpose gets one
line in the reply, or `<!-- writing: allow <term> -->` in the document. Never
silence a finding by deleting the fact it sits in. Then read `eval.md` against
the result and say what changed in the structure, what the linter flagged and
the fidelity result. If fidelity is not clean, say so instead of delivering.

**Detect** (audit, no rewrite). Do not touch the artifact. Name each pattern,
quote a short line, give the fix in a few words. Say where a table, diagram or
figure would beat the prose and what the reader would gain, without building
it. No score, no claim that a model wrote it. When the audited text carries
evidence (a cost report, a metric, a test result), check its discipline:
measured, estimated and verified stay in separate buckets and are never added
together; an empty result is an absence of signal, not zero; a cause only with
a comparison against a control or an earlier window, never from an aggregate
or a single case; every finding cites the id and the window it came from; what
is plausible without proof goes in a "Not proven" block with the next
read-only check.

**Calibrate** (there are samples, there is no draft). Read every sample and
measure what `references/voice-profile.md` lists: sentence length and spread,
paragraph length, openings, dash and quote habits, register, words the person
repeats on purpose, what they never do. Write the profile in that format, with
one quoted line from the samples under each observation, derived only from the
samples, and hand it back for editing. Apply it with `--profile <file>` on the
linter; it overrides the mechanical sweep and nothing else. A **product or
brand** voice (landing page, interface, public release) comes from the
project's brand guide and its published copy, with tone axes and "X, not Y"
traits; interface microcopy has its own rules. Both are in
`references/voice-profile.md`.

**Compress** (there is an original, the reader is an agent). Prose only
(`.md`, `.txt`); never code, config or a file with a secret's name. Keep the
original outside the tree, compress in place (drop articles, padding,
courtesy, repetition; keep code, paths, commands, numbers, dates, names,
headings, negations and qualifiers identical) and run the gate:

```bash
ORIG=$(mktemp); cp <file> "$ORIG"
python3 -I "$WRITING/scripts/fidelity_check.py" "$ORIG" <file>
```

MISSING or INVENTED puts the passage back. REVIEW you check sentence by
sentence: "you should run" → "run" passes with `--accept-semantic`; "never do"
→ "do" does not. Say how much came out and the result. Rules in
`references/lean.md`.

## Fix loop

The rules constrain the draft before it exists; the scripts and `eval.md`
inspect it afterwards. Between the two there is a loop, not a rewrite:

1. Lint. Read each finding with the severity ladder in SKILL.md.
2. Rewrite only the sentences the findings are in, only enough to remove the
   finding. Never regenerate the whole draft: a second full pass produces a
   second set of tics and loses the voice the first one kept.
3. Lint again. Stop at zero ERROR, with every WARN kept justified in one line.
4. In Edit, the fidelity check comes last, on the final text: every rewrite in
   step 2 is a chance to lose or invent a fact. A finding that only goes away
   by changing a fact is declared, not fixed.

The scripts are detectors, not proof. They prove that the hashed regions are
identical and that the chosen tokens add up. They do not read the meaning of a
whole sentence, so the final semantic pass (negation, modality, cause,
decision) is yours. Prose reviewed by the model that wrote it is not evidence:
that is why the scripts and `eval.md` exist. Weighty text (proposal, external
report, PR) goes through the `verifier` before it leaves.

## Mechanical sweep

Run it on the final text every time, from tier 1 up. It is cheap and catches
what reading your own prose lets through.

- **Em and en dashes.** Remove `—` and `–`, unless the writer's sample uses
  them. Replace with a full stop, comma, colon or parentheses. None in a short
  text; 1 or 2 in a long text when they clearly earn it.
- **Curly quotes.** Replace `“ ” ‘ ’` with straight ones, unless the format
  asks for curly.
- **Title Case Headings.** Capitalise only the first letter, proper nouns
  aside.
- **After a colon.** Lower case, unless grammar, a proper noun, a title or
  code requires otherwise.
- **Emoji.** None, in a heading or anywhere, unless it is the house
  convention.
- **Bold.** Only for a term being defined or a warning label (DESTRUCTIVE).
  Not for emphasis inside a sentence.
- **List of bold labels.** A list where every item is `- **Label:** sentence`
  is usually two sentences of prose.
- **Hyphenated compounds (English).** A hyphen before the noun (`a
  high-quality report`), no hyphen after it (`the report is high quality`).
- **Code block** for everything the reader will paste. A command ready to run,
  a placeholder such as `<TENANT_ID>`.
