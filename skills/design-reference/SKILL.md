---
name: design-reference
description: The squad's single method for interface design and visual art — direction before code, a verifiable quality floor, anti-patterns that give away AI-generated UI, motion with rules, tokens as the source of truth, and routing to the right skill already installed (frontend-design, ui-ux-pro-max, sumi, design-system, ui-styling, figma, canvas/algorithmic-art). Use when creating or redoing any screen, component, landing page, dashboard, mobile app, poster, graphic piece, generative art, canvas or design system, and when auditing existing UI. Merges the best of frontend-design (Anthropic), Impeccable, Emil Kowalski, Web Interface Guidelines (Vercel), UI/UX Pro Max and DESIGN.md (Stitch).
---

# design-reference — an interface that becomes a reference, not a template

An interface is a reference when someone who knows the subject recognises it
as made **for this product** and by **someone at the top of the field**. The
enemy is the default: what any model would produce for any similar brief.

## 0. The project rules

Before any decision, look for and read, in this order: `DESIGN.md` or
`PRODUCT.md` at the root; the brand guide (`brand/`, `docs/design*`); tokens
that already exist (`globals.css`, `tailwind.config.*`, `tokens.json`, theme);
the shared components the new screen will use. **The brief and the visual
world already committed to beat any taste of yours and any rule in here.**
Refining preserves identity, copy and behaviour; redesigning replaces the
whole visual world — never polish the look that was discarded.

Without a `DESIGN.md` the project is not necessarily greenfield: the evidence
is the code and the existing screens, not the file name.

## 1. Surface mode (decides everything that follows)

Choose by the **surface requested**, not by the product:

| Mode | Visitor's success | Examples | What rules |
|---|---|---|---|
| Persuade | decides and acts | landing page, pricing, campaign | attention, proof, call to action — design *is* the product |
| Operate | completes a task | app, dashboard, admin, editor, settings | scannability, consistency, native expectation; the brand lives in the detail |
| Read | understands something | docs, article, changelog, help | structure for comprehension, then reading comfort |
| Experience | is inside the work | portfolio, gallery, museum, showcase | the work leads from the first fold; the interface steps back |

The landing page of a tool is Persuade; the documentation of a fashion brand
is Read; the tour of a museum is Experience.

## 2. Direction before code (two passes, mandatory)

**Pass 1 — compact plan**, before opening any code file:

- **Subject:** one sentence: who it is for, what the single job of this screen
  is, and what in the world of *this* subject (materials, instruments,
  vocabulary, artefacts) can become a visual choice.
- **Colour:** 4–6 named values (hex or oklch), with the semantic role of each.
- **Type:** 2+ roles — a display face with character used with restraint, a
  complementary body face, a utility face for data if needed. Never the pair
  you would use on any other project.
- **Layout:** concept in one sentence + ASCII wireframe. Compare two alternatives.
- **Signature:** the **single** element the screen will be remembered for. All
  the boldness goes there; the rest stays quiet and disciplined.
- **Motion:** one orchestrated moment, or none. Say which.

**Pass 2 — self-critique.** For each item, ask: "would I produce this for a
similar brief from another product?" If yes, it is a default, not a choice —
rewrite it and say what changed. Only after that start coding, deriving every
colour and typeface from the plan.

The three looks AI produces by default today: (1) cream `#F4F1EA` + a
high-contrast serif + terracotta; (2) near-black + one acid accent (lime green
or vermilion); (3) a broadsheet of thin rules, zero radius, dense columns. All
legitimate **if the brief asks for them**. Where the axis is free, do not
spend the freedom on them.

For a catalogue of styles, palettes and type pairings with local search, use
`ui-ux-pro-max` (`python3 scripts/search.py "<domain> <product>"`); it is a
reference engine, not an art director — the decision is still yours.

## 3. Tokens are the source of truth

- Three layers: primitive → semantic → component. A component never reads a
  primitive or a raw hex; it reads `--color-surface-raised`, not `--gray-100`.
- Format: W3C DTCG 2025.10 (`tokens.json`) when the project has a pipeline;
  otherwise, CSS custom properties on `:root` with dark mode in
  `@media (prefers-color-scheme: dark)` and `[data-theme]`.
- Colour in oklch when possible; contrast measured (APCA or WCAG), not estimated.
- A dark theme is a luminance mapping, not an inversion.
- When you finish, if the project has no `DESIGN.md`, **offer** to generate
  one (tokens in YAML + the reason for each value in prose) — it is what keeps
  the next session coherent with this one.

To generate the complete system: `sumi:tokens` (DTCG + CSS/Tailwind) or the
`design-system` skill (component specs). One of the two, not both.

## 4. Build

- Stack and components: the project's. shadcn/Tailwind → `ui-styling`; a
  design coming from Figma → `figma:figma-design-to-code` (MCP) or the
  project's own local skill (for example `implement-from-figma`,
  `refactor-frontend-component`); writing to Figma → `figma:figma-use`.
- Native mobile: respect the platform (HIG / Material) before the brand.
- Real content from the start: test short, medium and very long copy; empty
  state; loading; error; no permission. Lorem placeholder is a defect.
- Copy is design material: a control says what happens ("Save changes", not
  "Submit"); the same verb from the button to the toast; an error says what
  happened and how to get out; empty is an invitation to act; active voice,
  sentence case.
- CSS: watch for specificity that cancels itself out (`.section` × `.cta`),
  `transition: all` never, only `transform`/`opacity` animate by default.
- Browser surfaces are design too: text selection, caret, scrollbar, focus,
  underline offset, tabular numerals. Theme them from the palette — it is the
  cheapest sign that the page was *built*.

## 5. Quality floor (verified in the result, not in the intention)

Read `references/quality-floor.md` immediately before editing UI. The
non-negotiable points:

- Contrast ≥ 4.5:1 (text), ≥ 3:1 (large); secondary text on a coloured surface
  tinted from that surface's own hue, never grey.
- Visible focus on everything interactive; never remove an outline without a
  replacement.
- Touch target ≥ 44×44 (native) / 24×24 CSS px (web), 8px between targets.
- `prefers-reduced-motion` respected; animation interruptible; nothing
  keyboard-initiated animates.
- Responsive down to 320px with no horizontal scroll; safe areas in full-bleed
  layout.
- Image with declared dimensions; font with `font-display`; long list
  virtualised.
- States: hover, active, focus, disabled, loading, error, empty — all of them.
- Zero emoji as icons; icons from one library, one stroke, one weight.

**Inspection in limited rounds, not in a loop:** build the whole thing,
capture desktop and mobile together (screenshot through the browser when there
is one), fix everything in one batch, confirm with at most one more round,
stop. Open-ended QA burns the owner's money doing worse what `sumi:audit` does
better.

## 6. Motion with rules (Emil Kowalski)

1. **Should it animate?** 100+ times/day (shortcut, palette) → never. Dozens/day
   (hover, list navigation) → reduce drastically. Occasional (modal, drawer,
   toast) → standard. Rare (onboarding, celebration) → it may delight.
2. A declared **purpose**: spatial continuity, state indication, explanation,
   feedback, avoiding a hard cut. "It looks nice" is not a purpose for
   something seen frequently.
3. **Easing:** enter/exit → strong ease-out `cubic-bezier(0.23, 1, 0.32, 1)`;
   move/morph on screen → ease-in-out `cubic-bezier(0.77, 0, 0.175, 1)`;
   hover/colour → `ease`; constant movement → `linear`; iOS drawer →
   `cubic-bezier(0.32, 0.72, 0, 1)`. **Never ease-in in UI.**
4. **Duration:** button 100–160ms; tooltip 125–200ms; dropdown 150–250ms;
   modal/drawer 200–500ms; UI always < 300ms except marketing.
5. Nothing appears out of nowhere: `scale(0.95) + opacity 0`, not `scale(0)`.
   A popover scales from its trigger (`transform-origin`); a modal stays
   centred. `:active` with `scale(0.97)`. One identical entrance on every
   section is an anti-pattern; one authored moment is not.

## 7. Art, canvas and creative work

When the request is a poster, cover, graphic piece, generative art, 3D visual
or "something beautiful with no UI brief", the method changes: first a
**visual philosophy** (a movement named in 1–2 words + 4–6 paragraphs on
space, colour, material, scale, rhythm, composition), then the execution. The
reference to the theme is subtle — those who know it feel it, the others see a
masterful composition. 90% visual, 10% text. Nothing leaves the margin,
nothing overlaps.

| Surface | Tool |
|---|---|
| static PNG/PDF (poster, art, cover) | `vendor/canvas-design` (Anthropic) |
| 2D generative art, flow fields, particles | `vendor/algorithmic-art` (p5.js, reproducible seed, sliders) |
| 3D / shader / interactive scene | three.js (r160+), GLSL `ShaderMaterial`; **always** `dispose()` and listener removal on teardown |
| piece for social media / ad / banner | `banner-design` or `design` (claudekit) |
| slides | `slides` |
| logo, icon, identity | `design` (logo/CIP/icon) + `brand` |
| side-by-side variants on an infinite canvas | `superdesign` plugin (paid; needs login — the owner's decision) |
| generated image/video | `sumi:generate` or the configured image MCPs |

Never copy the work of an identifiable artist; cite the influence, create your
own. Fonts: download and self-host one with the right character; the "closest"
system font is a failure, not a fallback.

## 8. Auditing and fixing what already exists

- Quick score with top fixes: `sumi:roast`. Full audit (heuristic, cognitive,
  flow): `sumi:audit`. WCAG 2.2 AA accessibility: `sumi:a11y`.
  Web checklist (a11y, forms, motion, typography, performance, i18n):
  `references/quality-floor.md` §B, output as `file:line`.
- Fixing generated UI code: `sumi:fix`. Motion review: a
  `| Before | After | Why |` table, one row per finding.
- Never load more than **two** design skills in the same session: the
  descriptions compete and the context swells without improving the answer.

## 9. Delivery

```
Mode             [Persuade | Operate | Read | Experience]
Direction        [subject · named palette · type pairing · signature · motion]
What was default [what you rewrote in the self-critique and why]
Tokens           [file and layers; DESIGN.md generated/updated?]
Floor            [each check from §5 with the measured value, not "ok"]
States           [list of the states implemented]
Captures         [desktop + mobile, if the environment allows]
Pending          [assets only the owner can supply; decisions that are theirs]
```
