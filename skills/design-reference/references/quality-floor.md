# Quality floor and anti-patterns

Load this after the direction has been decided and immediately before editing
UI. A fixed brief or the project's already committed visual world beats any
item in here; your habit does not.

## A. Verify in the built result (Impeccable, craft floor)

- **Contrast:** body and placeholder ≥ 4.5:1, large text ≥ 3:1. Secondary text
  on a coloured surface tinted from the hue or from the foreground; never grey.
- **Depth:** a shadow has an offset and a soft blur. A coloured halo with no
  offset is decoration.
- **Space:** tight groups, generous separation, more space above a heading
  than below it. Read the computed values.
- **Type:** body measure 65–75ch; display ≤ 6rem; minimum tracking -0.04em;
  balanced headings (`text-wrap: balance`); obvious steps of scale and weight.
  Run the real copy at every breakpoint and fix whatever overflows.
- **Motion:** one authored moment, not scattered effects nor the same entrance
  on every section. Exponential ease-out from an already visible state. Blur,
  `backdrop-filter`, `clip-path`, mask and shadow join the palette when they
  stay smooth.
- **States:** hover, disabled, loading, error, empty. Plus real content,
  working controls, responsive composition, keyboard focus.
- **Browser surfaces:** selection, caret, scrollbar, focus ring,
  `text-underline-offset`, tabular numerals — theme them from the palette.
- **Copy:** the product's language. A control names the action; an error names
  the problem and the way out.
- **Coverage:** every requirement in the brief present and findable in seconds.

### Refuse by default (the brief can win any of them back — except the one marked)

Page skeletons:
- Cards of the same size (icon + title + text) as the structure of the page.
  The card is the lazy container; a card inside a card is always wrong.
- The "hero metric" template: big number, small label, supporting stats,
  accent.
- **Kicker/eyebrow above the heading — banned, no brief wins it back.**
  The heading carries its own weight.
- Section numbering (01 / 02 / 03) unless the sequence carries information the
  reader needs.
- A modal for a task that needs neither interruption nor protected focus.

Surface habits:
- Gradient text. Emphasis comes from weight or size.
- Glass and blur as decoration, rather than as a specific effect.
- Coloured `border-left`/`border-right` above 1px on a card, item, callout,
  alert.
- Hard offset shadow (`box-shadow: 4px 4px 0`) outside a genuinely
  neobrutalist world.
- Sparkline, progress ring and rounded rectangle with a soft shadow in place
  of content.
- Monospace as a "technical" costume instead of for code, data, measurement.
- A system display font (Impact, Arial Black, the platform's sans) as the
  voice of a page with a world of its own. Download and self-host the right one.
- A Unicode glyph or emoji in place of an icon system.
- A geometric mask (circle, polygon, radial gradient) pretending to be the
  organic outline of a photo. Derive an alpha matte from the image or produce
  the cutout.
- Light or dark chosen by category. Choose by the scene of use: who, where,
  under what light.

## B. Web checklist (Web Interface Guidelines, Vercel) — output as `file:line`

**Accessibility.** An icon-only button has an accessible name; every form
control has a label; everything interactive works by keyboard; a native
element (`button`, `a`, `label`, `table`) before ARIA; `alt` on a meaningful
image, a decorative one hidden; an asynchronous update announced
(`aria-live="polite"`); headings in order without skipping a level; skip link;
media with captions/alternative and keyboard control.

**Focus.** Visible indicator; never `outline: none` without a replacement;
prefer `:focus-visible`; grouped focus in a composite control; fixed UI does
not cover the focused element.

**Forms.** `autocomplete`, a meaningful `name`, correct `type` and
`inputmode`; pasting allowed; clickable label; `spellcheck=false` on e-mail,
code, username; submit enabled until the request starts, spinner during it,
inline error with focus on the first one; a placeholder is an example ending
in an ellipsis; a warning before losing an unsaved change.

**Animation.** Reduced motion respected; only `transform` and `opacity`;
transitioned properties listed explicitly (never `all`); correct
`transform-origin`; interruptible; long autoplay has a pause.

**Typography.** Ellipsis character (…), curly quotes, non-breaking space where
it fits; a loading label ends in …; tabular numerals in a numeric column;
`text-wrap: balance`/`pretty` on a heading.

**Content.** Long text truncates or wraps; a flex child can shrink
(`min-width: 0`); empty state handled; test short, medium and very long.

**Image.** Explicit dimensions (CLS); lazy below the fold, priority above it.

**Performance.** Long list virtualised; no layout read during render; DOM
reads and writes batched; cheap controlled input; `preconnect` to the asset
domain; critical font preloaded; muted looping video instead of a GIF.

**Navigation and state.** UI state reflected in the URL; a real link
(modifier-click works); a destructive action confirms or offers undo.

**Touch.** `touch-action: manipulation`; intentional tap highlight;
`overscroll-behavior: contain` on a modal; no text selection and an inert
element during drag; a touch and keyboard alternative for a gesture;
`autofocus` rare.

**Safe areas and layout.** `env(safe-area-inset-*)` in full-bleed; no
horizontal scroll; layout by CSS, not JS measurement.

**Dark mode.** `color-scheme` on the root; `theme-color` meta equal to the
background; native `select` styled explicitly.

**i18n.** `Intl` for dates and numbers; language from the browser preference,
not the IP; brand and code tokens marked as non-translatable.

**Hydration.** Controlled input with a handler; a rendered date guarded
against server/client mismatch.

**Hover.** Button and link with feedback; hover, active and focus stronger
than the resting state.

**Copy.** Active voice; a numeral for a count; a specific label; an error with
what to do next; second person.

**Anti-patterns to flag:** a viewport that disables zoom; paste blocking;
`transition: all`; outline removed; a click handler on a non-semantic element;
inline navigation without a link; an image with no size; a large list without
virtualisation; an input or icon button with no label; hardcoded date/number
format; unjustified `autofocus`; a GIF where a video would do; a
gesture-only action.

## C. Motion — review table (Emil Kowalski)

| Before | After | Why |
|---|---|---|
| `transition: all 300ms` | `transition: transform 200ms var(--ease-out)` | explicit property; `all` animates what it should not |
| `transform: scale(0)` | `scale(0.95); opacity: 0` | nothing in the real world appears out of nowhere |
| `ease-in` on a dropdown | custom `ease-out` | ease-in delays the start, exactly where the user is looking |
| no `:active` on the button | `:active { transform: scale(0.97) }` | the button has to respond to the touch |
| `transform-origin: center` on a popover | `transform-origin` at the trigger | a popover is born from where it was called; a modal stays centred |
| animation on a keyboard shortcut | none | an action repeated 100+ times/day never animates |
| slow spinner | faster spinner | perceived speed goes up with the identical load |

Curves: `--ease-out: cubic-bezier(0.23, 1, 0.32, 1)`;
`--ease-in-out: cubic-bezier(0.77, 0, 0.175, 1)`;
`--ease-drawer: cubic-bezier(0.32, 0.72, 0, 1)`. Do not invent a curve:
easing.dev or easings.co.

## D. Mobile and native (UI/UX Pro Max)

Target ≥ 44×44pt (Apple) / 48×48dp (Material), 8px between targets; no
reliance on hover; press feedback (ripple / highlight); the platform's
standard gesture never redefined; a system gesture never blocked; the primary
target away from the notch, the Dynamic Island and the gesture bar; swipe with
a visible affordance; a movement threshold before starting a drag; Dynamic
Type/system text scale without truncation; `accessibilityLabel`/`Hint` with a
logical reading order; an escape route (cancel/back) in every modal and
multi-step flow.
