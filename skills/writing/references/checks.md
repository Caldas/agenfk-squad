# What the scripts detect, and what they get wrong

Prose reviewed by the model that wrote it is not evidence. These two scripts are
deterministic, run offline, need nothing beyond the Python standard library, and
produce output a human can check line by line.

## slop_lint.py

```
python3 scripts/slop_lint.py FILE [FILE ...] [--json] [--warn-as-error] [--allow TERM]
                             [--profile FILE]
```

Exit 0 clean or warnings only, 1 on any ERROR, 2 on usage error.

**Declaring a term intentional.** `--allow strategic`, repeatable, or
`<!-- writing: allow strategic, journey -->` inside the document itself
(`<!-- writing: allow-emoji -->` for emoji; the older `escrita:` spelling is
still read). A declared term is still
reported, marked `(declared intentional)`, but drops to WARN so it does not
block delivery. The finding stays auditable; only the gate relaxes. This is the
answer to a legitimate word tripping the lexicon: declare it, do not delete the
fact it sits on and do not weaken the check for everyone.

**Applying a voice profile.** `--profile FILE` reads the profile a Calibrate
job wrote (`voice-profile.md`): a YAML file, or a markdown file whose first
`yaml` fence holds it. The linter reads four keys and ignores the rest. `allow`
is a list of terms, treated like `--allow`. `dashes: writer` switches off
`dash-density` and `tight-dash`, because for a writer whose own sample is full
of em dashes the checks encode a default habit, not a fact. `quotes: curly`
switches off `curly-quotes`, and `emoji: allow` demotes `emoji` to WARN. Nothing
else changes: a banned construction, a generic heading, a certainty adverb or a
nominalization chain is a finding under any profile, because none of those is a
habit a writer keeps on purpose. A profile that cannot be read is a usage error
(exit 2), not a silent default.

**Blockquotes.** A finding inside a blockquote drops to WARN with a note, because
a blockquote is usually a quotation or a before/after example: someone else's
words, which this skill never rewrites silently.

Everything runs on prose only. Fenced code, inline code, YAML frontmatter, HTML
comments, markdown tables and link targets are masked before any check, so no
finding can land on material the fidelity rules require to stay verbatim.

Multi-word constructions are tested on each line and on that line joined with the
next, because hard-wrapped markdown routinely splits a construction across a line
break. A finding is reported at the line where the construction starts.

Masking covers: fenced code, inline code with any number of backticks, YAML
frontmatter, single- and multi-line HTML comments, GFM tables with or without the
leading pipe, link targets and bare URLs.

| Check | Severity | Detects | False positives |
|---|---|---|---|
| `banned-lexicon` | ERROR | robusto, abrangente, transformador, jornada, ecossistema, estratégico, alavancar, escalável, plus the English set: utilize, facilitate, foster, streamline, empower, paradigm, holistic, synergy, tapestry, paramount, testament, showcase, pivotal, interplay, vibrant, nestled, renowned, groundbreaking, elevate, embark, supercharge, multifaceted, meticulous, intricate, garner, enhance, ever-evolving, state-of-the-art, disruptive | High by design. "Decisão estratégica" in a strategy document is correct. Justify and keep |
| `banned-construction` | ERROR | não é apenas X é Y, vale destacar, mergulhar profundamente, desbloquear o potencial, em sua essência, in the realm of, de suma importância, this changes everything, chatbot residue, throat-clearing, faux insight, announcing the next point, generic and recap endings, knowledge-limit disclaimers, importance puffery | Low. These shapes are almost never load-bearing |
| `soft-construction` | WARN | weasel attribution, shallow -ing clauses, serves/stands as a, boasts/features a, weak verb phrases, fake alternatives, unraised objections, metadiscourse, pseudo-revelation, stacked hedges, formulaic sayings, false from-X-to-Y ranges | Medium. A design document may legitimately reject a real alternative; an FAQ may legitimately answer an objection. Read `false-positives.md` |
| `banned-heading` | ERROR | Visão abrangente, Principais insights, Destaques estratégicos, Considerações finais, Jornada de implementação, bare Introdução/Conclusão/Overview/Key takeaways/Final thoughts | Low |
| `title-case-heading` | WARN | Headings In Title Case Like This | Fires on headings that are mostly proper nouns |
| `heading-monotony` | WARN | Three or more headings opening with the same word | Legitimate in a numbered series ("Fase 1", "Fase 2") |
| `forced-tricolon` | WARN | "A, B e C" with three near-identical item lengths | Fires on real three-item sets. Confirm the third is a fact |
| `list-over-prose` | ERROR >45%, WARN >35% | Bullets as a share of body lines | Legitimate in a checklist or pure reference document |
| `long-bullet-run` | WARN | Seven or more consecutive bullets | Same |
| `bold-label-list` | WARN | Three or more consecutive `- **Label:** sentence` items | Legitimate in a glossary or an options table written as a list |
| `uniform-rhythm` | WARN | Sentence-length standard deviation under 4.5 words over 8+ sentences | Fires on short reference documents |
| `long-sentence` | WARN | Sentences over 45 words | Sometimes correct in a contractual clause |
| `repeated-paragraph-opening` | WARN | Three or more paragraphs opening with the same word | Low |
| `bold-density` | WARN | More than 3 bold spans per 100 words | Fires on documents using bold as a term-definition convention |
| `dash-density` | WARN | More than 1.2 em/en dashes per 100 words, spaced or not | Fires on writers who genuinely use dashes. Keep the writer's rate |
| `curly-quotes` | WARN | `“ ” ‘ ’` | macOS, Word and most CMSes auto-curl. Only a tell when stacked with others |
| `tight-dash` | WARN | An em or en dash with no space on either side (`palavra—palavra`) | None. Always wrong in this style, at any density |
| `emoji` | ERROR | Any emoji | Intentional in some announcements |
| `filler` | WARN | basicamente, essencialmente, obviamente, claramente, simplesmente, plus English | Low |
| `unsupported-certainty` | WARN | undoubtedly, certainly, undeniably, clearly, obviously, it is clear that, there is no doubt, sem dúvida, inegavelmente, certamente, é evidente que | Medium. "Clearly" inside a quoted instruction, or a product name. The fix runs one way: show the evidence or keep the hedge, never strengthen |
| `transition-density` | WARN | Three or more generic connectives (furthermore, moreover, additionally, consequently, on the other hand, além disso, ademais, por outro lado, nesse sentido, dessa forma) at over 0.8 per 100 words | Low. Causal connectives (because, therefore, however, as a result) are not counted. One finding per document, listing the lines |
| `nominalization` | WARN | Two or more abstract nouns (implementation, optimization, alignment, enablement, utilization, implementação, otimização, alinhamento, habilitação) in one sentence | Medium. A sentence that names two real deliverables ("the implementation and the optimization both ship in 1.4") trips it. One abstract noun per sentence never does. Paragraph sentences only: a chain inside a list item is not scanned |
| `uniform-paragraphs` | WARN | Five or more paragraphs whose word counts vary by under 20% around a mean of 20 words or more. Lists and headings are not paragraphs | Fires on a reference document written as equal entries. A template filled in looks the same, which is the point |
| `chatbot-artifact` | ERROR | "como um modelo de linguagem", "as an AI model", chatbot openings in the first lines | None |
| `portability` | WARN | Sentences of 10+ words with no number, proper noun or project term | Highest false-positive rate in the suite. A definition or a transition can legitimately be generic |

Two ERROR checks have a high false-positive rate on purpose: `banned-lexicon` and
`emoji` should cost a sentence of justification rather than pass silently.

### Terms deliberately not banned

`gate`, `gating`, `harness`, `key`, `pipeline` and `underscore` appear on generic
AI-slop word lists and are absent here, because in technical material they are the
precise word: AgEnFK step gates, the agent harness, an API key, the CI pipeline.
`beacon` stays out for the same reason (`navigator.sendBeacon`), and the bare
`realm` because of auth realms; only the filler construction "in the realm of"
is flagged. `crucial` and `actually` sit in the `SKILL.md` guidance lists but
not in the lexicon, because each has a common legitimate use that a per-hit
error would punish. `landscape` is banned only as an abstract noun. See
`false-positives.md`.

## fidelity_check.py

```
python3 scripts/fidelity_check.py ORIGINAL REWRITE [--json] [--allow-added]
                                  [--accept-semantic] [--ignore REGEX]
```

Exit 0 clean, 1 on any difference, 2 on usage error.

**This is a detector, not a proof of fidelity.** It proves two narrow things: the
hashed regions are byte-identical, and the selected tokens balance. It does not
understand a sentence. Read the limits at the bottom before you quote it as
evidence.

It is for **Edit** only. For new content there is no original, so the gate is a
coverage list built from the sources, checked item by item. Running it against an
empty or unrelated file produces a clean result that means nothing.

### Regions compared byte for byte

| Region | How |
|---|---|
| YAML frontmatter | SHA-256 of the whole block |
| Fenced code | SHA-256 per block, with its first line for identification |
| Inline code | Every span, counted, whitespace-normalized, any backtick count |
| HTML comments | SHA-256 per comment, single- or multi-line |
| Link targets | The full destination, absolute or relative |
| Markdown table rows | Normalized, with or without leading pipes |

### Fact tokens compared as multisets

URLs, ticket keys (`INFRA-264`), versions, dates, currency, percentages,
quantities with units, AWS account and resource ids, ARNs, CIDRs, IPs, file
paths, snake_case / kebab-case / CamelCase / UPPER_SNAKE identifiers, file names
with a known extension, and bare numbers.

`MISSING` means the original had it and the rewrite does not: information you
dropped. `INVENTED` means the reverse: information you made up. Both fail.
Rewording is invisible to this diff, which is the point. It compares facts, not
sentences.

### REVIEW: vocabulary that flips meaning

Token diffs cannot catch `approved` becoming `not approved`, because no token
moved. So the script also profiles meaning-flipping vocabulary and reports every
count that changed:

- **negation**, as one aggregate: not, no, never, without, neither, nor, não,
  nunca, jamais, sem, nem, tampouco. Aggregated on purpose, so swapping "not X"
  for "without X" stays quiet while adding or dropping a negation does not.
- **polarity**, per term: approved, rejected, enabled, disabled, public, private,
  allow, deny, reversible, irreversible, and the pt-BR equivalents.
- **modality**, per term: must, shall, should, may, required, optional,
  mandatory, deve, deverá, pode, obrigatório, opcional.
- **direction**, per term: before, after, increase, decrease, raise, reduce,
  antes, depois, aumentar, reduzir.

A REVIEW line blocks (exit 1) and is **not a verdict**. The script never decides
whether the change is right. Read both sentences; if the change was intended,
re-run with `--accept-semantic`. Acknowledging semantics does not excuse a
MISSING or INVENTED token: those still fail.

### Escape hatches

`--allow-added` downgrades INVENTED to a warning. Use it only when the user asked
for new content in the same pass, and say so in your report. `--ignore` takes a
regex, repeatable, for a token or a REVIEW key you removed with the user's
agreement.

### What it still cannot do

A reversed meaning built from vocabulary outside the four semantic groups. A fact
swapped for another of the same shape does show up, as one MISSING plus one
INVENTED. Fidelity remains a rule you follow, not a rule a script enforces, and
the final semantic pass over negations, modality, causality and decisions is
yours.

## artifact_check.py

```
python3 -I scripts/artifact_check.py page.html [other.html ...]
```

Exit 0 when every page passes, 1 on any `FAIL <rule>`, 3 when a file could
not be read (not checked, which is not the same as failed). A `WARN` never
fails. The rules, by name:

| Rule | When | Fails on |
|---|---|---|
| `title` | Every page | No `<title>` with text |
| `tokens` | Every page | No `:root{...}` rule defining custom properties. A missing dark mode is only a WARN |
| `ds-contract` | Every page | A `var(--ds-*)` no `:root` defines: the design-system block was not pasted |
| `local-image` | Every page | An `<img src>` or `<image href>` pointing at a local path |
| `toggle` | `data-languages` with two or more languages | The first element of `<body>` is not a visible `.langbar` with one `data-lang` button per language |
| `i18n` | Same | The `#i18n` payload is missing, keys differ between languages, a value is empty, a `data-t`/`data-t-aria` key is absent, visible text sits outside `data-t`, or no script reads `#i18n` |
| `initial-language` | Same | `<html lang>` is not the first declared language (`pt` matches `pt-BR`) |
| `export` | Same | No `html.render .langbar{display:none}` rule |
| `languages` | A `.langbar` or `#i18n` is present | The page does not declare `data-languages` |

False positives: low. A page that legitimately points at a local image for a
local preview fails `local-image` on purpose, because a published Artifact
breaks it; use inline SVG, a URL or `data:`.

## selftest.sh

```
bash scripts/selftest.sh
```

Proves every checker still catches what this file claims. Its temp file is created
with `mktemp`, so parallel runs cannot read each other's output.

| Fixture | Guards |
|---|---|
| `slop.md`, `clean.md` | pt-BR detection, and no false positive on clean pt-BR |
| `slop-en.md`, `clean-en.md` | English detection; `clean-en.md` uses `gate`, `harness`, `key` and `pipeline` and must stay at 0 ERROR |
| `ambiguous-en.md`, `ambiguous.md` | Shapes that resemble a pattern and are the right sentence: a contrast between two mechanisms, a passive with an unknown actor, one abstract noun, one transition, one real qualifier. 0 ERROR, and none of `unsupported-certainty`, `transition-density`, `nominalization`, `uniform-paragraphs` |
| `dashes-writer.md` + `voice-profile.yaml` | A dash-heavy text reports `dash-density` and `tight-dash` alone, and neither under the profile; the profile's `allow` list downgrades a lexicon word on `allowlist.md` |
| `masking.md` | GFM table with no pipes, multi-line HTML comment, double-backtick inline code, blockquote demotion, tight dash |
| `allowlist.md` | A legitimate lexicon word blocks by default and drops to WARN under `--allow` |
| `adversarial-fidelity-original.md` + `-rewrite.md` | Changed frontmatter, inline code, link target, HTML comment, added negation, private to public. None may pass |
| `adversarial-fidelity-original.md` + `faithful-rewrite.md` | A real reword of the same original must come back clean |
| `templates/document.html`, `templates/document-bilingual.html` | The shipped templates pass `artifact_check.py` as they are; variants derived from them fail `languages`, `initial-language`, `export`, `ds-contract`, `title` and `local-image` |
| `artifacts/neutral.html`, `artifacts/bilingual.html`, `artifacts/bilingual-incomplete.html` | A neutral and a complete bilingual page pass; a bilingual page missing half of a language fails `toggle` and `i18n`; a page without `:root` tokens fails `tokens` |

Run it after editing either script or any rule table.
