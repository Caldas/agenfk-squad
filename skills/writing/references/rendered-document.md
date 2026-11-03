# Rendered document

This applies to whatever a person opens as a document: an HTML page, an
Artifact, a report or runbook as a page, and the PDF generated from it. Text
that renders no image (commit, chat reply, code comment, plain-text email, PR
body, AgenFK card, markdown in `docs/`) takes none of this: it follows only the
text rules in `SKILL.md`.

The division of labour: this skill owns the **text** (fidelity, structure,
lexicon, language). The **look** belongs to the project's design system or,
without one, to the `design-reference` skill. Neither adds a house logo or
brand.

## 1. The project's system wins

Run the sweep once per project, the first time you render for it, and keep the
result for the session. In a monorepo, run it in the document's workspace. The
sweep belongs to `design-reference` (full rules in
`design-reference/references/design-system-sweep.md`):

```bash
S=~/.claude/skills/design-reference/scripts/sweep.py
python3 -I "$S" <root>          # says what it found and where, and the conflicts
python3 -I "$S" <root> --css    # :root block with --ds-* (and dark) to paste into the template
```

| Finding | Verdict |
|---|---|
| `DESIGN.md` or a written spec (`docs/design-system.md`, a Figma link in the README) | Read and follow it. It beats what the code suggests |
| A tokens or theme file with named colour, spacing and type | Design system. Paste the tokens into the page's `:root` |
| A component library in use (in-house, shadcn in `src/components/ui`, MUI, Radix) | Reuse the components where the medium allows; on a static page, mirror them with the tokens |
| Storybook | The rendered components are the truth |
| Only the library's default style, nothing customised | Not a design system. Use the neutral template |
| A client's logo and palette in the client's repository | Third-party brand. Ask the owner before using it |

When two disagree, the written spec wins, then the tokens, then the
components. State the conflict in one line.

How to dress the page: replace the `--ds-*` block at the top of the template
with the `--css` output, without re-deriving colour from a screenshot or a
logo; load the project's fonts where the template uses the system font; one
design system per page. Say in one line which system the page wears and where
you found it; a sweep with no finding gets the same line.

No access to the repository, or a standalone document: skip the sweep, say so
and use the neutral template.

A document that already exists keeps the look it has. A text edit never
changes the look of a page.

## 2. Neutral template

`templates/document.html` is the starting page, with or without a system in
the project. It brings:

- at the top, the `--ds-*` block (the sweep's contract) with the squad's
  neutral palette as the default; with a system in the project, that block is
  replaced by the `--css` output and nothing else changes;
- semantic tokens in `:root` (`--bg`, `--surface`, `--text`, `--text-muted`,
  `--accent`, `--font-display`, `--font-text`, `--font-mono`) that read only
  `--ds-*`, plus the page's own `--ok`, `--warn`, `--danger`; a component reads
  only the semantic token;
- dark mode through `@media (prefers-color-scheme: dark)` and through
  `<html data-theme="dark|light">`, as `design-reference` asks;
- the system font, with no download, and tabular numbers;
- a 72-character measure, body text from 16px, visible focus,
  `prefers-reduced-motion` respected;
- small components: `.eyebrow`, `.lede`, `.meta`, `.callout`, `.note`,
  `.status` (with a word next to the colour, never colour alone), a table in
  `.tbl-wrap` with `td.n` for numbers, `pre code` for what gets pasted.

No logo, no brand, no mandatory font. If the page needs its own identity
(colour, type, a visual signature), that is work for `design-reference` and
the `frontend` agent, not for this skill.

The `h1` and every `h2` state the finding, not the subject. "Restoring staging
takes 42 minutes" is a title; "Test results" is a label.

## 3. Language and toggle

The document's language follows the rule in `SKILL.md`: what the owner asked
for, the language of the existing artifact, the repository's policy, otherwise
English. **One language by default.**

A language toggle is optional: only when the audience is bilingual or the
owner asked. Then start from `templates/document-bilingual.html` and declare
the languages on the root:

```html
<html lang="en" data-languages="en pt">
```

- The first language in `data-languages` is the one the page opens in, and
  `<html lang>` starts with it (`pt` matches `pt-BR`).
- The `.langbar` is the first element of `<body>`, with one `data-lang` button
  per declared language.
- Every visible text sits in an element with `data-t="<key>"`; the markup
  carries the text in the opening language, so the page reads right before the
  script runs. Names, numbers and code that are not translated take
  `translate="no"` or stay in `code`/`pre`.
- `<script type="application/json" id="i18n">` holds one object per language,
  with the same keys. The template's script swaps text through `textContent`
  (it injects no HTML).
- The choice comes from `#en`/`#pt` in the URL, then `?lang=`, then the last
  choice (`localStorage`, key `writing-language`), then the first declared
  language.
- `html.render .langbar{display:none}`: an export comes out without the bar,
  one PDF per language.

The second language is a translation of meaning, written under the same rules
as the first; numbers, names, commands and code stay identical in both, and
technical terms stay in English.

## 4. Exporting to PDF

One PDF per language, with headless Chrome on Linux:

```bash
for l in en pt; do
  google-chrome --headless=new --no-pdf-header-footer --virtual-time-budget=4000 \
    --print-to-pdf="$PWD/page-$l.pdf" "file://$PWD/page.html#$l"
done
```

A single-language page: one command, without the fragment. `@media print`
hides the bar and keeps the theme with `print-color-adjust: exact`. To check
the phone width, open the page in a 390px iframe; headless Chrome does not draw
below roughly 500px.

## 5. The check

```bash
python3 -I "$WRITING/scripts/artifact_check.py" <file.html>
```

It exits 1 and names the rule when the page has no `<title>` (`title`),
defines no tokens in `:root` (`tokens`), uses a `var(--ds-*)` that no `:root`
defines, meaning the sweep's block was not pasted (`ds-contract`), or points an
`<img src>` at a local path (`local-image`). On a page that declares two
languages it also requires the complete bar (`toggle`), the payload with the
same keys in every language and no text outside `data-t` (`i18n`), the opening
language (`initial-language`) and the export rule (`export`). A page with a
`.langbar` or `#i18n` but no `data-languages` fails (`languages`): a
half-built toggle does not escape. A missing dark mode is only a warning. It
exits 3 when it could not read the file: the page was not checked, which is
not the same as failed.

The hook `hooks/writing-artifact.py` runs the same check before an Artifact is
published and asks the owner for confirmation when it fails. Registering the
hook in `settings.json` is the owner's decision.
