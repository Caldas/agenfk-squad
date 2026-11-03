# Lean mode, commit message and Compress

Three uses of the same principle: every token is paid twice, by whoever
generates it and by whoever reads it, and the fact survives every cut. Code,
command, path, number and error are the payload; one changed character breaks
the payload. Ceremony is expensive, grammar is cheap. A lost negation costs
more than all the tokens saved: clarity beats compression.

## Lean mode (tier 0: chat and terminal status)

**Turns on** with an explicit request ("lean mode", "caveman", "be brief",
"fewer tokens") and **stays on** for the whole session, until "normal mode" or
"stop lean mode". When in doubt whether it still applies, it does. Turning it
off is confirmed in one line.

1. **Answer first.** Answer, then reason, then next step. Shape:
   `[thing] [action] [reason]. [next step].`
   Bad: "Sure! I'd be happy to help. The issue you're seeing is likely…"
   Good: "Bug in auth middleware. Token expiry uses `<`, not `<=`. Fix:"
2. **Zero ceremony.** No greeting, no recap, no offer of help at the end, no
   "I'll now", no "just", "really", "basically", "actually".
3. **Short words.** "fix", not "implement a solution for". Standard acronyms
   are fine (DB, API, HTTP); invented abbreviations are not (cfg, impl, fn):
   same tokens, worse reading. No arrows instead of verbs.
4. **Articles optional, meaning never.** Drop an article when the sentence
   still reads in one pass; a fragment is fine. **Never drop** not, never, no,
   only, except. Exact number and unit.
   Bad: "Migration drops column backup first."
   Good: "Back up first. Then run the migration: it drops the column."
5. **One idea per sentence.** At most 20 words, active voice, imperative in an
   instruction, one term per thing, a pronoun only with an obvious referent.
6. **Payload verbatim.** Code blocks untouched. Commands, paths and API names
   exact. An error quoted exactly, only the decisive line. A code change in the
   chat: the changed lines and 1 or 2 of context, not the whole file (the whole
   file only if asked, if the file is new or if almost everything changed). An
   existing comment in a file you edit is payload too: do not delete or shorten
   it unless asked.
7. **Tool status kept short.** Nothing between routine calls. One line before a
   multi-step job, one per phase change, one with the result. Otherwise, text
   before a call only to clarify, warn or disambiguate.
8. **The requester's language.** Compress the style, do not switch the
   language. Technical terms and error messages stay as they are.
9. **Never perform the mode.** No "lean mode on", no prefix, no normal answer
   followed by the short version, no decorative table or emoji. If the short
   version is not shorter than the plain sentence, use the plain one.

**When to break the rule** (full sentences, then back to the mode):

1. A security warning.
2. An irreversible action: confirm it in full sentences first.
3. An order of steps a fragment would scramble.
4. The requester is confused or repeats the question.
5. Everything recorded outside the chat: code, comment, commit, doc, issue,
   PR, card, memory, a message to a third party. Those follow the skill's tiers
   1 and 2, not this mode (the Compress job is the exception, below).
6. The harness asks for a status line or a confirmation: give it. It decides
   *when* to speak; the mode decides *how*.
7. You ask a question or offer options: full sentences, so the answer comes
   back right the first time.

**Check before sending**

1. Does the first sentence announce what you are about to do? Delete it.
2. Does the last one recap or offer help? Delete it.
3. Is every not/never/only still there? Every code, path, number and error
   verbatim?
4. Any sentence with two readings? Write it out in full.

## Commit message

Read the repository's convention first: `git log --oneline -20`,
`CONTRIBUTING`, `CLAUDE.md`/`AGENTS.md`. **The project's convention beats**
everything here (language, prefix, capitalisation, trailers). With no visible
convention, use Conventional Commits.

- **Subject:** `<type>(<scope>): <summary in the imperative>`, scope optional.
  Types: `feat fix refactor perf docs test chore build ci style revert`.
  Imperative ("add"), not past tense. ≤ 50 characters when possible, ceiling
  72, no full stop.
- **Body** only when needed: the why the diff does not show, a breaking
  change, a migration note, a linked issue. Wrap at 72 columns, items with
  `-`, references at the end (`Closes #42`).
- **Body required** for a breaking change, a security fix, a data migration
  and a revert: whoever debugs later needs the context.
- **Never goes in:** "this commit does X", "I", "we", "now", "currently" (the
  diff says what); "as requested by" (use a trailer); emoji outside the
  convention; repeating the file name the scope already says. AI attribution
  only as a trailer, and only when the owner's or the project's rule asks for
  it.
- The skill **writes** the message. `git commit`, staging and amending belong
  to whoever asked.

```
feat(api)!: rename /v1/orders to /v1/checkout

BREAKING CHANGE: clients on /v1/orders move to /v1/checkout
by 2026-06-01. After that the old route returns 410.
```

## Compress (context file)

Shrinks a `CLAUDE.md`, `AGENTS.md`, memory, handoff or task list an agent
reads every session, keeping **every fact**. It runs locally, with no external
API: you do the compressing, and the gate is `fidelity_check.py`.

**Prose only:** `.md`, `.txt`, no extension. Never `.py .js .ts .json .yaml
.toml .env .lock .css .html .sql .sh` nor a file with a secret's name (`.env`,
`credentials`, `secrets`, `.netrc`): refuse before reading it. A mixed file:
only the prose changes. When in doubt whether it is code or prose, leave it.

**Drop:** articles where the sentence still reads in one pass; padding (just,
really, basically); courtesy ("feel free to", "I recommend"); ceremonial
hedges ("it might be worth considering", "it would be good to"); long
phrasings ("in order to" → "to", "make sure to" → the imperative); decorative
connectives (furthermore, moreover); "you should", "remember to" (state the
action); items that repeat the same thing in other words; the second example
of the same pattern.

**Keep identical:** code blocks (down to comments and spacing), inline code,
URLs and links, paths, commands, technical and library names, proper names,
dates, versions, numbers, environment variables, section headings (the exact
text), frontmatter, list hierarchy, numbering and table structure. Never drop
a negation, "only", "except", "unless" or a qualifier that is the content.

**Steps:**

```bash
ORIG=$(mktemp); cp <file> "$ORIG"                          # copy outside the tree
# ... compress <file> in place ...
python3 -I "$WRITING/scripts/fidelity_check.py" "$ORIG" <file>
```

A non-zero exit blocks. MISSING or INVENTED is a fact lost or created: put the
passage back. REVIEW (negation, modality, polarity) you check sentence by
sentence; "you should run" → "run" is intended and passes with
`--accept-semantic`; "never do" → "do" never passes. Say in the reply how many
lines or words came out and the fidelity result. Do not save the original next
to the file (an automatic loader would read both); if the owner wants to keep
it, outside the tree.

An example of what counts:

> Original: "You should always run the test suite before opening a pull
> request against the main branch. This is important because it helps catch
> bugs early and prevents broken builds from reaching production."
>
> Compressed: "Run the test suite before opening a pull request against the
> main branch: catches bugs early, keeps broken builds out of production."

## Origin

Adapted from `JuliusBrussee/caveman` (Apache-2.0), skills `caveman`,
`caveman-commit` and `caveman-compress`; the local fidelity gate replaces the
API compressor. Attribution in `THIRD_PARTY_NOTICES.md`.
