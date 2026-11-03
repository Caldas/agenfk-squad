# Motion in Figma: the `use_figma` scripts

Load `figma:figma-use` and `figma:figma-use-motion` first (that is the MCP's
rule; pass `skillNames: "figma-use,figma-use-motion"` on every call). File,
motion nodes and variable collections: the project's
`.claude/design-bridge/PROJECT.md`. Below, `<MOTION_NODE>` is the motion
section node it names.

## 0. Probe (always the first call)

The motion API may not be enabled on the account. A single read-only call; if
it returns `"<name>" is not a supported API`, **stop**: the card goes
`blocked` with the literal message, with no retry.

```js
const out = { keyframes: false, figmaStyles: null, customStyles: false };
const node = await figma.getNodeByIdAsync("<MOTION_NODE>");
try { void node.manualKeyframeTracks; void node.timelines; out.keyframes = true; } catch (e) { out.keyframesError = String(e); }
try { out.figmaStyles = figma.motion.figmaAnimationStyles().map((s) => s.name); } catch (e) { out.figmaStylesError = String(e); }
try { await figma.getLocalCustomAnimationStylesAsync(); out.customStyles = true; } catch (e) { out.customStylesError = String(e); }
return out;
```

Record the result in a card comment: it decides which of the skill's flows
exist on this account.

## 1. Stage: layers named after the code

The code owns the values, so Figma needs the same skeleton:

- One top frame per motion (`Motion · BrandSting · light`); the timeline
  belongs to the top frame, and **the top frame is never animated**: only its
  children.
- Each animated layer is named exactly `<layerPrefix><name>` (the `layer`
  that `export` returns): it is the join key, the equivalent of
  `data-node-id`. The drawing's parts come out of the code as SVG; import them
  with `figma.createNodeFromSvg` and rename them.
- **Pivot:** Figma rotates and scales around the node's visual centre. When
  `export` returns a non-null `pivot` (e.g. origin `828.1px 674.2px` in the
  viewBox), wrap the layer in a transparent frame **centred on the origin
  point** and animate the frame. Never compensate with translation: the maths
  breaks with rotation and scale together.

## 2. Apply the tracks the code exports

```bash
<adapter from PROJECT.md> > "$TMP/animations.json"
node ~/.claude/skills/design-bridge/scripts/motion-figma.mjs export "$TMP/animations.json" <prefix> > "$TMP/tracks.json"
```

Paste the JSON's `layers` into `LAYERS`. Unit factor: `px` is a drawing unit,
so multiply by `PX_PER_UNIT` (height in Figma ÷ viewBox height); `%` is of the
box itself (X by width, Y by height). Scale, rotation and opacity do not
convert.

```js
const STAGE = "<id of the top frame>";
const PREFIX = "<layerPrefix>";
const PX_PER_UNIT = 0.4; // Figma px per drawing unit (e.g. a 400 px symbol in a viewBox 1000 high)
const LAYERS = [/* layers from export */];

const stage = await figma.getNodeByIdAsync(STAGE);
const factor = (c, field, node) =>
  c.unit === "px" && field.startsWith("TRANSLATION") ? PX_PER_UNIT
  : c.unit === "%" && field === "TRANSLATION_X" ? node.width / 100
  : c.unit === "%" && field === "TRANSLATION_Y" ? node.height / 100
  : 1;
const mutated = [], missing = [];
let end = 0;
for (const c of LAYERS) {
  if (Object.keys(c.tracks).length === 0) continue;
  const node = stage.findOne((n) => n.name === c.layer);
  if (!node) { missing.push(c.layer); continue; }
  for (const [field, track] of Object.entries(c.tracks)) {
    const f = factor(c, field, node);
    node.applyManualKeyframeTrack({ type: "PROPERTY", name: field }, {
      keyframes: track.keyframes.map((k) => ({ ...k, value: { type: "FLOAT", value: k.value.value * f } })),
    });
  }
  end = Math.max(end, c.endS);
  mutated.push(node.id);
}
const target = stage.findOne((n) => n.name.startsWith(PREFIX));
const [timeline] = target ? target.timelines : [];
if (timeline && timeline.duration < end) { target.setTimelineDuration(timeline.id, end); mutated.push(timeline.id); }
return { mutated, missing, timelines: target?.timelines };
```

A non-empty `missing` means the stage is incomplete; complete it before going
on. Loop (`loopMode: "loop"`) is a timeline property in Figma: check it in the
read-back (`timelineCohorts` from `get_motion_context`) and set it in the panel
if the API does not expose it.

## 3. Read back and compare with the code

The same conversion, inverted, to return to drawing units:

```js
const STAGE = "<id>", PREFIX = "<layerPrefix>", PX_PER_UNIT = 0.4, UNITS = {/* layer → "px" | "%" | null, from export */};
const stage = await figma.getNodeByIdAsync(STAGE);
const readBack = {};
for (const node of stage.findAll((n) => n.name.startsWith(PREFIX))) {
  const u = UNITS[node.name];
  const div = (field) =>
    u === "px" && field.startsWith("TRANSLATION") ? PX_PER_UNIT
    : u === "%" && field === "TRANSLATION_X" ? node.width / 100
    : u === "%" && field === "TRANSLATION_Y" ? node.height / 100 : 1;
  const tracks = {};
  for (const [field, t] of Object.entries(node.manualKeyframeTracks ?? {})) {
    if (!t?.keyframes) continue;
    tracks[field] = { keyframes: t.keyframes.map((k) => ({
      timelinePosition: k.timelinePosition,
      value: { type: "FLOAT", value: Number((k.value.value / div(field)).toFixed(4)) },
      ...(k.easing ? { easing: k.easing } : {}),
    })) };
  }
  if (Object.keys(tracks).length) readBack[node.name] = tracks;
}
return readBack;
```

Save the result to `$TMP/read-back.json` and run
`motion-figma.mjs compare "$TMP/animations.json" "$TMP/read-back.json" <prefix>`.
It exits `0` with `equal`, or `1` with the list of what diverges. **A
divergence is never resolved by editing the number in Figma:** values change
in the code (with a test), and Figma is reapplied.

## 4. See the motion: `export_video` + frames

`get_screenshot` only shows the resting state. To review the motion:

1. Pick the moments first (4–6: start, each phase, settling). For a 1.8 s
   entrance: 0 · 0.36 · 0.72 · 1.1 · 1.5 · 1.8 s.
2. `export_video` of the **top frame**, `constraint: {type:"WIDTH", value:768}`,
   `quality:"low"`, `fps: 5`. It renders on the server and is slow: one
   round, fix everything in a batch, at most one more.
3. `ffmpeg -ss <t> -i anim.mp4 -frames:v 1 f_<t>.png` for each moment.
4. Compare side by side with the code's reference frames (folder in
   `PROJECT.md`), rendered from the components themselves. A visible
   difference means a wrong stage (pivot, name, unit), not a wrong value:
   `compare` already guaranteed the value.

## 5. UI in Figma: animation styles bound to a variable

For **UI** motion (menu, popover, toast, dialog), Figma's best feature is the
reusable animation style whose duration is **bound to the UI duration
variable** (collection in `PROJECT.md`): change the token and every screen
changes; switch the collection to the reduced-motion mode and the whole screen
shows the reduced mode. Build it as a custom style
(`figma.createCustomAnimationStyle`) made of the native definitions (Fade,
Move, Scale), with a name that states the token (e.g. `ui/menu-enter` →
duration `base` + curve `enter`).
If the probe said `customStyles: false`, the flow does not exist on this
account: say so and stop, without falling back to manual keyframes on your
own.

Whether the variable follows the collection's mode inside the style: check it
on first use with one `export_video` per mode. Until then, it is a hypothesis.
