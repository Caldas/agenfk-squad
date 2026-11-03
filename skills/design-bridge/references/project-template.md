# Setting up the bridge in a project

Each project keeps what is **its own** in `.claude/design-bridge/`:

```
.claude/design-bridge/
  PROJECT.md          # this template, filled in
  animations.<ext>    # adapter: prints the animations in the contract below (if flow A exists)
```

The skill and the agent belong to the squad; nothing project-specific goes into them.

## `PROJECT.md` (template)

```markdown
# Design bridge: <project>

## Enabled worlds
| World | State | Why / since |
|---|---|---|
| Code | yes | |
| Figma | yes · file `<fileKey>` | |
| Claude Design System | no / proposed / yes · `<artifact url>` | owner's decision on <date> |
| GPT (Codex, ChatGPT plan) | yes / no | owner's decision on <date>; card with the vendor comparison |
| Local ComfyUI | yes / no · GPU `<model, VRAM>` | |

## Figma
| What | Node |
|---|---|
| Brand motion page/section | `<id>` |
| UI motion section | `<id>` |
| UI motion variable collection (modes) | `VariableCollectionId:<id>` |
| Brand motion collection (if any) | `VariableCollectionId:<id>` |

## Tokens
- UI motion: `<file>` (names `<pattern>`); values in reduced mode.
- Brand motion: `<file>` (names `<pattern>`), if the project separates them.
- Source of truth: `<code file>`; Figma is reapplied from it.

## Motion in code
- Stack: `<own WAAPI/CSS | motion/react | GSAP | …>` (and the decision that chose it).
- Reduced-motion hook: `<import>`.
- Adapter: `<command that prints the JSON>` · layer prefix: `<prefix>`.
- Reference frames from the code (to compare with `export_video`): `<folder>`.

## Generated assets
- Inbox: `~/.local/state/<project>/design-inbox/` (outside the repo).
- Brand destination: `<folder>` · screen destination: `<folder>` · `origin.json` next to each asset.
- Format tools available: `<potrace, svgo, sharp, ffmpeg…>`.
- ComfyUI recipes: `<folder>` · allowed weights and licence: `<table or link>`.

## Owner rules that change the bridge
- <e.g. screens are born in Figma; visual acceptance belongs to the owner>
- <e.g. no new spend without authorisation; what is already fixed>
- <e.g. generator scope: our own assets only, never client creative>
```

## Adapter contract (flow A)

The adapter prints **one JSON document** on stdout. A neutral example, for a
toast that rises into place:

```json
{
  "source": "src/motion/animations.ts",
  "layerPrefix": "ui-",
  "easings": { "motion/ui/easing/enter": "cubic-bezier(.2,.8,.2,1)" },
  "animations": [
    {
      "name": "toast-enter",
      "durationMs": 1800,
      "iterations": 1,
      "delayMs": 0,
      "box": "fill-box",
      "origin": "50% 100%",
      "defaultEasing": "linear",
      "frames": [
        { "offset": 0, "opacity": 0, "transform": "translate(0px, 12px) scale(0.9) rotate(0deg)", "easing": "cubic-bezier(.17,.85,.28,1.12)" },
        { "offset": 0.4, "opacity": 1, "transform": "translate(0px, 0px) scale(1) rotate(0deg)" },
        { "offset": 1, "opacity": 1, "transform": "translate(0px, 0px) scale(1) rotate(0deg)" }
      ]
    }
  ]
}
```

- `frames` in the Web Animations API keyframe format: `offset` 0–1, `easing`
  applies to the segment that **starts** at the frame (the script shifts it to
  the Figma convention), only `transform` (`translate`/`translateX|Y`,
  `scale`/`scaleX|Y`, `rotate` in deg/turn/rad) and `opacity`.
- Translation unit: `px` (of the drawing) or `%` (of the box), one per
  animation. The `use_figma` script converts it to node pixels.
- `iterations`: an integer or `"infinite"`. `box`/`origin` other than
  `fill-box`/`50% 50%` mark a pivot.
- `easings`: token name → value, only so the report can say which token each
  segment uses (or `NO TOKEN`).

The adapter **reads** the project's animation module; it is never the source
of the numbers.
