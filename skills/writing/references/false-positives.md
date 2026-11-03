# What not to flag, and what to protect

The failure mode of this skill is over-application: sanding a real voice into
generic polished prose, or reporting patterns that are just how a person writes.
Read this before any Detect job and before editing prose that is not yours.

Rule of thumb: **one signal proves nothing.** One em dash, one *however*, one
short sentence for emphasis. Several stock patterns in the same passage are the
evidence. When unsure, look for co-occurrence.

## Not evidence by itself

- **Perfect grammar and consistent style.** Many writers are professionals or have
  been edited. Polish is not AI.
- **Bland or dry prose.** AI prose has specific tells. Dryness without those tells
  is just dry writing.
- **Formal or academic vocabulary.** The word lists target words AI overuses, not
  every formal word. Do not simplify a precise term into a common one.
- **Mixed casual and formal register.** Reflects the writer's field, age or habits.
- **Common transition words in isolation.** *Additionally*, *moreover*,
  *consequently* are a tell only when piled up.
- **Curly quotes.** macOS, Word, Google Docs and most CMSes auto-curl by default.
  They count only stacked with other tells.
- **Em dashes.** Many editors and journalists use them heavily. Evidence only when
  paired with sales-y rhythm.
- **One short sentence for emphasis.** Flag dramatic fragments only in a row.
- **Deliberate repeated openings.** "She came. She saw. She conquered." Change it
  only when the repetition adds nothing.
- **"Honestly" or "look" mid-sentence.** Ordinary in casual writing. The tell is
  the standalone theatrical opener.
- **Useful limits and disclaimers.** Keep scope statements, safety and legal
  notices, real corrections, named objections, replies, FAQ answers.
- **Real alternatives.** Keep options a reader would actually consider in a design
  document or ADR. Remove only the unlikely option the text dismisses and never
  uses again.
- **Unsourced claims.** Most writing is unsourced. That alone proves nothing.
- **Clean complex formatting.** Templates and visual editors produce it without AI.
- **Secondhand text.** Never rewrite a watched phrase inside a quotation, a title,
  a proper name, or an example where the phrase is being discussed rather than used.
- **Anything written before 2022-11-30.** ChatGPT's public launch.

## Shapes that look like a pattern and are the right sentence

The checks are regexes and the catalogue is a list of shapes. Genre decides
whether a shape is a tell, and these are not, in the documents this skill
mostly edits:

- **A contrast between two concrete mechanisms.** "This is not HTTP polling;
  the client keeps a WebSocket open" names two things that exist and says
  which one runs. The fake version contrasts a plain fact with a bigger
  abstraction ("not just monitoring, proactive intelligence"). Keep the first.
- **Passive voice when the actor is unknown, irrelevant or the point.** "The
  bucket was created in 2024; the author is unknown." "The key is rotated every
  24 hours." Rewrite to active only when the reader needs to know who.
- **Necessary repetition in technical and operational text.** The same resource
  name, the same command, the same term in every step. Synonym cycling is the
  tell; repeating `acme-tfstate-stg` six times in a runbook is correct.
- **A set of three because there are three.** Three accounts, three stacks,
  three event types. `forced-tricolon` fires on rhythm, so confirm the third
  item is a fact and keep the list.
- **One qualifier that carries the writer's actual knowledge.** "May", "we
  estimate", "not yet measured", "inferred from staging". In security, legal,
  financial, medical and incident text the qualifier is the content. Stacked
  hedges are the tell; one honest hedge is information.
- **One abstract noun, one transition.** "The implementation reads the state
  once." "Moreover, the lock table is on-demand." The checks count chains and
  density, not single uses, and a single use is never the finding.
- **A conclusion when a decision is being asked for.** An executive note ends
  on the decision requested, with its date. The recap ending is the tell; a
  closing ask is the document's purpose.
- **Explicit structure in a reference document.** Headings, tables and
  numbered steps in a runbook or an API reference are navigation, not slop.
  `list-over-prose` and `heading-monotony` fire on them by design; justify and
  keep.

## Terms that are load-bearing here

These appear on generic AI-slop word lists and are deliberately **not** banned in
this skill, because in technical material they are the precise word:

| Term | Why it stays |
|---|---|
| `gate`, `gating` | AgEnFK step gates, CI required checks, approval gates |
| `harness` | the agent harness (Claude Code, Codex, Copilot) |
| `key` | API key, app key, partition key, KMS key |
| `landscape` | only banned as an abstract noun ("the evolving landscape") |
| `pipeline` | the actual CI/CD pipeline |
| `strategic` | correct in a strategy document. Justify and keep |
| `journey` | correct in a user-journey diagram, banned as "our journey" |

A flagged word you keep on purpose costs one line of justification in your reply.
It never costs the fact it sits on.

## Human details to protect

Keep these unless they damage the meaning. They are where voice lives.

- **Specific, unusual detail.** A real address, an odd quote, "the lawyer who used
  to work upstairs from my dentist".
- **Mixed feelings and unresolved tension.** "I think this is mostly good, but it
  bothers me and I can't fully explain why."
- **Dated, era-bound references.** Slang, memes, in-jokes tied to a year and a
  subculture. Models lag by a year or more.
- **Deliberate first-person choices.** A cut or a word the writer can defend.
- **Variety in sentence length.** Real writing alternates short and long. AI tends
  toward an even mid-length cadence, which is why `uniform-rhythm` is a check.
- **Genuine asides, parentheticals and self-corrections.** "(I keep wanting to say
  'almost' here, but it really was certain.)"
- **Edge and character.** Strong opinions, blunt language, humor, profanity,
  self-interruptions, honest admissions. Do not replace them with safer wording.
- **The writer's structure.** Preserve their progression and detours when they
  carry personality. If you reorganize, say why in `What changed`.

## Matching a writing sample

When the user supplies their own previous writing, analyse it before rewriting:
sentence length, word choice, paragraph openings, punctuation, repeated phrases,
transitions. Then match that, including the sample's dash rate. The sample
overrides the mechanical sweep, and it overrides these defaults, not the fidelity
rules. With two or more samples, run the Calibrate job and write the result down
in the format of `voice-profile.md`, so the next session starts from the profile
instead of re-reading the samples.
