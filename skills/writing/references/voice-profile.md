# Voice profile

A Calibrate job turns two or more samples of a person's writing into this file.
The person edits it and keeps it; the skill reads it at the start of every
later job and the linter reads four of its keys through `--profile`. It records
habits. It never records facts, and it never relaxes the fidelity rules or the
banned constructions, because none of those is a habit.

## Where it lives

Wherever the user keeps it. Two conventions, so a later session finds it
without asking:

| Scope | Path |
|---|---|
| One repository | `.writing/voice.yaml` at the repository root, committed if the team shares the voice |
| One person, every project | `~/.config/writing/profiles/<name>.yaml` |

Pass it to the linter as `python3 -I "$WRITING/scripts/slop_lint.py" --profile <path> <doc>`.
A profile can also sit inside a markdown file as its first `yaml` fence.

## Format

Flat `key: value` pairs and `- item` lists. No nesting, so the linter can read
it with the standard library. Every key is optional. The linter reads `allow`,
`dashes`, `quotes` and `emoji`; the rest is for the model.

```yaml
name: exemplo
language: pt-BR            # the language the samples are in; artifacts still follow SKILL.md
register: technical, blunt, first person only for the writer's own decisions
sentence_length: 8 to 30 words, with a short one for emphasis about once a paragraph
paragraph_length: 1 to 6 sentences, rarely the same two in a row
openings: the subject first; a connective opens fewer than one sentence in ten
dashes: none              # none | writer   (writer keeps the sample's em dashes)
quotes: straight          # straight | curly
emoji: none               # none | allow
contractions: yes         # en only
allow:                    # words on the banned list this writer uses with a meaning
  - strategic
repeats:                  # words and phrases the writer repeats on purpose
  - "the gate"
  - "which is why"
avoid:                    # what the samples never do
  - inspirational endings
  - announcing the document
  - rhetorical questions
```

`dashes: writer` switches off `dash-density` and `tight-dash`. `quotes: curly`
switches off `curly-quotes`. `emoji: allow` demotes `emoji` to a warning.
`allow` behaves like `--allow`: the finding stays visible, marked intentional,
and stops blocking. Nothing else in the linter reads the profile.

## How Calibrate derives it

Read every sample in full before writing a line of the profile. Then, for each
key, measure rather than impress:

1. Sentence length: the median and the spread, and whether short sentences
   appear alone (emphasis) or in rows (a tic to leave alone if it is theirs).
2. Paragraph length and whether it varies.
3. How sentences open: subject, connective, adverb, a quoted term.
4. Dashes, quotes, parentheses, semicolons, contractions, emoji: count them.
5. Register: formal or blunt, first or third person, humour, profanity,
   self-corrections, honest admissions. These are the voice; the profile exists
   so an edit keeps them.
6. Repeated words and phrases the writer clearly chooses, and words on the
   banned list they use with a precise meaning. Those go in `repeats` and
   `allow`.
7. What the samples never do. That is `avoid`, and it is the most useful key,
   because it is where an edit most often adds something the writer would not.

Under each observation in your reply, quote one line from the samples that
shows it, so the person can check the profile against their own words. A field
you cannot support with a quote stays empty. Never fill a field from what you
assume about the person, their role or their language: the profile is derived
from the samples alone.

## What it may never do

- Change a fact, a number, a name, a decision or a qualifier. Fidelity is not
  a habit.
- Excuse a banned construction, a generic heading or chatbot residue. A writer
  does not "have a voice" of announcing the document.
- Make the text informal because the person writes informal messages. A
  profile built from Slack posts applies to Slack posts; say so in `name` or
  keep two profiles.
- Stand in for the samples. When the samples are in the conversation, they
  win; the profile is what survives to the next session.

## The project's brand voice

When the text speaks **on behalf of a product or team** (landing page,
interface, product email, post, public release note), the voice comes from the
project, never from a brand fixed in the skill. Order of sources: brand guide
(`docs/brand*`, `BRAND.md`, the voice section of `DESIGN.md`) > the product's
published copy (README, interface, landing page) > the latest PR titles and
commits for the internal register. With none of these, ask for the tone in one
line; do not invent one.

Calibrating a product's voice uses the same profile format as above, with three
extra fields derived from the samples:

- **Voice and tone.** The voice is fixed (the personality); the tone changes
  with the context (celebration, support, error, legal). Record the tone per
  context the samples show.
- **Axes:** formal to casual, simple to technical, serious to playful,
  restrained to expressive, each with one quoted line that proves it.
- **Paired traits "X, not Y"** (e.g. "direct, not curt"), 3 to 5, each with one
  do and one don't taken from the samples.

The voice test: would a competitor say this sentence unchanged? If so, the
portability test is failing: replace it with a fact, mechanism or proof from
the product itself. The core and supporting messages always carry their proof
next to them (a number with a source, a customer who can be quoted, a feature
that exists today); a claim without proof does not go in.

### Interface text (microcopy)

- A control says what happens: "Save changes", not "Submit".
- An action keeps its name through the whole flow: the "Publish" button leads
  to the "Published" notice.
- Name things by what the person controls and recognises, not by how the
  system is built: "notifications", not "webhook configuration".
- An error says what happened and how to get out, in the interface's voice: it
  does not apologise and it is not vague.
- An empty state is an invitation to act, not mood.
- Active voice, sentence case, each element with one job only: a label labels,
  an example exemplifies.

Origin: the idea of the voice axes, paired traits and proof next to the
message comes from the claudekit `brand` skill (no licence claimed; written in
this skill's own words, see `THIRD_PARTY_NOTICES.md`); the microcopy rules from
`frontend-design` (Anthropic) and `design-reference`.
