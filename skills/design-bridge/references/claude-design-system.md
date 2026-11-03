# Claude Design System: the live mirror

## What it is (checked 2026-10-16)

Claude's "components" are the **Design System** artifact type: a README that
works as a brand book, `tokens.json` (colours per theme, typography, spacing,
radius), **components with a live preview and usage guide**, assets and
comments. Claude's decks and designs are built on top of it, and other agents
read its `project/README.md` instead of combing through the repo.

- To find it: `Artifact list` with `scope: "types"` shows the type and its
  `type_url`. `Artifact list` with `type: "Design System"` shows the systems
  the account already has.
- Standalone Claude Design (claude.ai/design) **closes on 2026-12-14**; the
  artifact type is what remains. Syncing through `DesignSync` /
  `/design-sync` targets standalone Claude Design projects: build nothing on
  top of it.
- The **Design** type (artboard canvas) uses the Design System to assemble
  screens and variations quickly, inside the session. It is for exploring;
  the screen record is still Figma.

## Where it beats the other worlds

| | Code | Figma | Claude Design System |
|---|---|---|---|
| Component preview **in motion** | only by running the app | only through `export_video` | **live, in the browser** |
| Read by an agent without opening the repo | no | through MCP, expensive | **yes, one README** |
| Owner comment anchored to the component | no | yes | yes |
| Source of the values | **yes** | no | no |
| Visual acceptance of a screen | no | **yes** | no |

That is why it is a **mirror**, never an origin: it is generated from the code
and from Figma, and never hand-edited as a source. An owner comment on it
becomes a card, the card changes the code and the mirror is generated again.

## Rules

- **Declared conflict of interest:** it is a product of the agent's own
  vendor. It is an **optional** layer, adopting it is the owner's call, and
  the repository and Figma stay complete without it (zero lock-in).
- **Only a Claude Code session** has the Artifact tool. Sessions on other
  runtimes (Codex, pi) do not, so no product card may depend on the mirror.
- Nothing from the mirror enters the product's runtime.

## Limitations of the type that change the work

- **There is no motion token family.** Motion goes in the README (a Motion
  section, with the token table) and in the previews.
- Previews load **React 18** by default. A component that uses a React 19
  feature (e.g. `<style href precedence>`) needs `react` and `react-dom` 19 in
  `components/lib/`, both together and pinned, or the preview stays frozen.
- `components/bundle.js` is **a classic script** that assigns
  `window.<Namespace>`, with no import and no network. Build it with the
  bundler the project already has (esbuild, which ships with `tsx`, will do).
- `tokens.json` is a **list**, not the DTCG format: each family is
  `{"tokens":[{name,value,usage}]}`. `var()` and `color-mix()` do not get in
  (the entry is dropped), so tokens coming from Figma need converting.
- Contrast 4.5:1 in every theme and every preview.

## How to build it (once the owner approves)

1. Create it from the `type_url`, read the type's `SKILL.md` and
   `artifact-type/reference/from-code.md` in the created artifact.
2. Take the full inventory before writing: tokens, components, motions, logos
   and mascot. Record what was left out.
3. Write everything into a scratchpad folder at `<dir>/project/…` and publish
   it in one call with `root`, leaving the index `project/design-system.json`
   **last**.
4. To revise later: read, change only what changed, and send the index again
   at the end.
5. Record the link in `PROJECT.md` (Enabled worlds).
