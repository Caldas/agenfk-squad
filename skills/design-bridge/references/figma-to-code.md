# Screen motion from Figma → code

Load `figma:figma-design-to-code` and `figma:figma-implement-motion` first
(the MCP's rule is to load them before `get_design_context` and
`get_motion_context`). Figma's method applies in full; here is **what the
bridge adds**.

## What Figma delivers and what we do with each piece

| What comes | Use it for | Do NOT use it for |
|---|---|---|
| `get_design_context` | structure, `data-node-id`, assets, layout | animation values |
| `get_motion_context(recursive: true)` | inventory of animated nodes, timing, easing, `timelineCohorts` | pasting into the code as is |
| `codeSnippets` (motion.dev / CSS) | **reading** the values faithfully | becoming a dependency the project did not decide on (`PROJECT.md` → stack) |
| `export_video` | showing the owner what the screen does | approving your own implementation |

## Value → token (the step Figma does not do)

Every duration and every easing from `get_motion_context` must land on a
project token (`PROJECT.md` → Tokens):

1. UI motion → UI tokens.
2. Brand motion → brand tokens and components. If the component already
   exists, use it instead of reimplementing it.
3. A value that matches no token (±10 ms or a different curve) is **drift**.
   Write `| node | value in Figma | nearest token |` on the card and choose:
   adjust Figma to the token (the default) or propose a new token (the
   owner's decision, it enters both sides in the same card). Never a loose
   literal.

## Implementation

- In the motion stack the project already uses. With no library: CSS
  `transition`/`@keyframes` with the token variables, or WAAPI when you need
  per-state control. Only `transform` and `opacity`.
- Reduced motion through the project's single hook; UI tokens go to zero in
  `@media (prefers-reduced-motion: reduce)`. There is no option to ignore it.
- The errors and warnings from Figma's export lint (`motion-lint-rules.md`) go
  into the report **with the literal text**. Prototype interaction (Smart
  Animate) does not come through the MCP: you get the start and the end, not
  the transition.
- Do not invent motion: a node with no data in `get_motion_context` stays
  still.

## Checking

- One animation end to end before replicating: e2e (Playwright) in a
  throwaway environment recording the segment, frames with `ffmpeg` at the
  same times as the `export_video`, side by side.
- E2E with `emulateMedia({ reducedMotion: 'reduce' })`: the final state
  appears without animation.
