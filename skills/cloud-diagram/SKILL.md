---
name: cloud-diagram
description: The squad's standard for cloud architecture diagrams (AWS, OCI, GCP, Azure, Alibaba, Cloudflare): a technical sheet in hand-drawn inline SVG, with groups nested in the provider's convention (cloud → region → VPC → zone → subnet), service icons in the category colours, a service spanning zones drawn as a dashed band, orthogonal arrows that never cross, numbered steps tied to the list, a stamp and a legend, the drawing's status in the stamp (CURRENT as of a date, or PROPOSED), an inventory with a source per node before the geometry, the page chrome dressed in the project's design system (the design-reference sweep), tokens in both themes, a probe that measures overlap, sideways scrolling and the status before delivery, and a .drawio deliverable with a gate (diagram_check.py) when asked for. Use it whenever you draw, redo or review an architecture, infrastructure, network or service-flow diagram for the cloud (in an Artifact, HTML page, doc, ADR, README or proposal), including when it goes with a cost quote (finops) or a design review (infra). It replaces mermaid, exported draw.io or generic boxes.
---

# cloud-diagram: the squad's architecture sheet

The standard grew out of an architecture drawing the owner approved, and it is
the reference for any cloud diagram. Before drawing, open the two files:

- `references/template.html`: the kit to copy. Light and dark tokens, the
  "diagram sheet" CSS block, the `<defs>` library (groups, services, items
  outside the cloud), a sample drawing and the steps script.
- `references/example.html`: a worked example on a fictional product (photo
  uploads, serverless, no VPC). It is an example, not a rule: it shows the
  floor of quality for the whole page (diagram, stamp, legend, linked steps,
  an inventory with a source per node).

Copy the kit and swap the drawing. Do not redesign the grammar on every request.

## 0. The project decides

A diagram skill of the project's own (`.claude/skills/`) wins over this one.
The **page chrome** (background, surface, text, accent, title and body font)
wears the design system of the project at hand:

```bash
python3 -I ~/.claude/skills/design-reference/scripts/sweep.py <root> --css
```

Paste the output in place of the `--ds-*` block in `template.html`; the rest
of the page reads only from it. With no design system in the project, the
built-in default stays (the neutral sheet). If
`design-reference/scripts/sweep.py` is not installed, the built-in default
stays too, and the line says the sweep was not run. The provider's category colours do
not change with the project and live only inside the diagram. The condensed
face on the labels (`--label`) still holds; if the project has a condensed
face, it goes there. Say in one line which system the page wears.

## 1. Content comes from whoever knows

The diagram shows the architecture that was decided, not an invented one. Cost
comes from `finops`, with source and date. Never add a service to "complete"
the drawing. Detail and examples in `references/inventory-and-drawio.md`.

- **Inventory before geometry.** List the nodes and arrows (type and label of
  each arrow) with the **source of each node**: IaC, state, a read-only read
  of the account (a `-ro` profile), ADR, card or request. What you assumed
  goes in a list and in the answer. Data missing: ask, or draw only what is
  certain.
- **Status stated.** The stamp says CURRENT as of YYYY-MM-DD (with the source)
  or PROPOSED. Before and after are two sheets, each with its own.
- **Audience.** Technical readers get service, protocol, port, CIDR, counts;
  executives get action labels and numbered steps, no implementation. Ask once
  if it is not obvious.
- **Two tests before drawing.** Isomorphism: every box is a real resource and
  every arrow a real flow, and the shape alone already says something.
  Education: the reader learns something a list would not give; if not, write
  the list.
- **Boundaries follow the real hierarchy.** Nest only what exists; a boundary
  drawn for tidiness looks like a security boundary.

## 2. The grammar (not negotiable)

**Sheet.** A `.sheet` with a 1.5 px border in the ink colour and its own
surface. Under the drawing, a **stamp** (`dl.stamp`, five cells: Status,
Region, Zones, Network, State; Status is CURRENT as of a date or PROPOSED,
State is about the application's state) and the **legend** (category colours,
"outside the cloud", solid call, dashed background). Below the sheet, the
`ol.steps` list "The path of …".

**Nested groups, outside in**, each level 16 px inside the previous one, with
a 20–22 px group icon at the top-left corner and the label beside it (`.gl`,
13 px, 500). A zone carries its label centred at the top.

| Level (AWS) | Stroke | Class |
|---|---|---|
| AWS Cloud | solid, squid ink | `g-cloud` + `c-cloud` |
| Region | round dotted `2 4`, teal | `g-region` + `c-region` |
| VPC | solid, purple | `g-vpc` + `c-vpc` |
| Availability Zone | dashed `8 5`, blue, no icon | `g-az` |
| Public subnet | filled light green, green outline | `g-sub` + `c-sub` |
| Private subnet | filled light teal, teal outline | `g-priv` + `c-priv` |

Global services (CloudFront, Route 53, IAM) sit inside the cloud and outside
the region. Regional services with no VPC (S3, SQS, DynamoDB, Lambda outside
a VPC, Secrets Manager) sit inside the region and outside the VPC, in a column
or band of their own.

**Service.** A square in the category colour with a white glyph of stroke 2
(`.gy`): 48 px for a managed service, 44 px for a task or instance, 36 px
inside a support group. A two-layer label: name in `.t` (14.5 px, 600, ink)
and up to three lines of detail (13 px, secondary ink), below and centred when
the icon sits in a row, to the right when it sits in a stack. The detail says
the role in the drawing ("job queue", "1 writer instance"), not the service's
definition.

**Service spanning zones** (ECS service, Auto Scaling group, cluster): an
orange dashed band `g-svc` across both zones, with one instance drawn in each
zone and the name in the middle. It shows multi-AZ without repeating the
service. Support tools that run together go in a `g-aux` group (dashed
`3 3`, neutral) with a title and "1 task each".

**Outside the cloud** (client, app, browser, third-party SaaS, Cloudflare,
push service, messaging app): a neutral outlined square (`k-ext`) with a glyph
in ink (`.gx`). Never use a third party's logo or brand colour. Clients on the
left, third parties the API calls above, outputs (push, email) on the right.

**Arrows.** Horizontal and vertical only, 1.5 px, a single marker (`#ah`).
They never cross; a fork gets a junction dot (`.jn`, r 3.5). A call is solid;
whatever runs in the background (queue, push, replica) is dashed `6 5`, and
only that dash moves, turned off under `prefers-reduced-motion`. An arrow never
runs over a label nor through an icon; it goes around the group.

**Numbered steps.** A balloon of r 11 (`g.st`, `data-s="n"`) on the step's
arrow; the `ol.steps` list has the same numbers, and the script lights both
together on pointer hover. Six steps is the right size; past eight, split into
two drawings.

**Colour.** The provider's category colours live only inside the diagram. The
page has a single accent (the lit balloon, the main series of a chart). Every
SVG text uses a text token, never the category colour.

## 3. Category colours

AWS (Architecture Icons; group values were darkened where contrast asked for
it, and dark mode lightens the strokes, not the squares):

| Token | Light | Dark | Category |
|---|---|---|---|
| `--aws-compute` | `#ed7100` | `#ed7100` | Compute (EC2, ECS, Fargate, Lambda) |
| `--aws-db` | `#c925d1` | `#c925d1` | Database (RDS, Aurora, DynamoDB) |
| `--aws-int` | `#e7157b` | `#e7157b` | Application Integration (SQS, SNS, EventBridge) |
| `--aws-storage` | `#7aa116` | `#7aa116` | Storage (S3, EFS) |
| `--aws-net` | `#8c4fff` | `#8c4fff` | Networking (CloudFront, ALB, Route 53, API Gateway) |
| `--aws-sec` | `#dd344c` | `#dd344c` | Security, Identity (Secrets Manager, Cognito, WAF) |
| `--aws-cloud` | `#232f3e` | `#c9d2da` | AWS Cloud group |
| `--aws-region` | `#00868a` | `#2fc4c6` | Region group |
| `--aws-vpc` | `#8c4fff` | `#a98bff` | VPC group |
| `--aws-az` | `#147eba` | `#55aee6` | Zone group |
| `--aws-subnet` / `-fill` | `#7aa116` / `#f0f5e2` | `#93c01f` / `#17231a` | public subnet |
| `--aws-private` / `-fill` | `#00868a` / `#e3f2f2` | `#2fc4c6` / `#122226` | private subnet |

## 4. Other providers

The grammar is the same; the levels and the palette change.

| Provider | Levels, outside in |
|---|---|
| OCI | Tenancy → Region → Compartment → VCN → Availability Domain (→ Fault Domain) → Subnet |
| GCP | Organization/Project → Region → VPC (global) → Zone → Subnet (regional) |
| Azure | Subscription → Resource group → Region → VNet → Zone → Subnet |
| Alibaba | Account → Region → VPC → Zone → vSwitch |
| Cloudflare | edge outside the project's cloud; Workers, R2, D1 in a "Cloudflare" group of their own |

Another provider's category colours come only from its official icon kit, with
the URL and date in a CSS comment. Without the kit checked, use the AWS palette
by category and say so in the legend; do not invent a brand's palette.

## 5. Layout before coordinates

1. List the nodes and the arrows with each one's step.
2. Lay out a grid of columns: clients | edge | cloud (zones side by side) |
   regional | outputs. Third parties in a row above. Main flow left to right,
   asynchronous going down.
3. Trace the arrows on paper (ASCII) before writing the SVG; if two cross,
   move a node, do not draw over it.
4. A `viewBox` about 1200 wide, integer coordinates, labels at least 12 px
   clear of the arrows and of the group borders.
5. The SVG sits in `.scroll > .dia` with `min-width:1040px`; under 1120 px the
   "swipe sideways" hint appears. The page body never scrolls sideways.

## 6. Page contract

- SVG with `role="img"` and an `aria-label` that narrates the whole flow in
  prose; the scroll container with `tabindex="0"`, `role="region"` and a label.
- Chrome read from the `--ds-*` block (section 0); the sheet maps `--page`,
  `--surface`, `--ink`, `--accent` and the fonts from it.
- Tokens in `:root`, redefined in `@media (prefers-color-scheme: dark)` under
  `:root:not([data-theme="light"])` and in `:root[data-theme="dark"]`. No
  literal colour in the SVG outside the tokens (the white glyph is a token too).
- No external image, icon or fetch: everything inline. Fonts only from Google
  Fonts, with a condensed fallback stack.
- Sheet typography: the project's title and body (`--ds-font-*`), condensed on
  the diagram labels (Barlow Semi Condensed in the template).
- In an Artifact, load the Artifact page contract skill too; with a cost chart
  alongside, a data-visualisation skill. For `frontend`, this skill is the "one
  design skill" next to `design-reference`.

## 7. Verification (before delivering)

```bash
~/.claude/skills/cloud-diagram/scripts/render.sh <page.html> <folder> "1100 400"
```

It writes `shot-<theme>-<width>.png` in both themes and runs the probe: label
over label, label over icon, balloon over label, arrow cutting a label, arrow
through an icon, arrow crossing an arrow away from a junction, body scrolling
sideways, fonts loaded, and the stamp's **Status** cell (CURRENT with a date or
PROPOSED; without it, or "current" with no date, it fails). Chrome comes from
`$CHROME` or from `google-chrome`/`chromium` on the PATH. Under 500 px the page
runs in an iframe of the exact width, because headless Chrome opens no smaller
window. Exit 1 = it found a problem; exit 2 = no Chrome to render with.

The probe measures geometry; the eye measures reading. Open the 1100 px shots
in both themes and check: group hierarchy readable, nothing cut off, contrast.
Fix everything in one batch, run once more, stop.

## 8. When asked for .drawio

The HTML page with the inline SVG is the default editable source. If the owner
asks for draw.io: official `mxgraph.aws4` shapes with a checked stencil name,
the file saved uncompressed, the preview exported with the XML embedded, every
edge attached at both ends, and the gate:

```bash
python3 -I ~/.claude/skills/cloud-diagram/scripts/diagram_check.py name.drawio
```

It fails bad XML, a compressed page, a duplicate id, a floating edge, a label
that reads as AI-written (the `writing` skill's lexicon, or a small built-in
one when that skill is not installed) and a drawing with no CURRENT-with-a-date
or PROPOSED. Then render it and look. Rules and the full table in
`references/inventory-and-drawio.md`; a clean fixture in `fixtures/clean.drawio`.

## 9. Delivery

```
Status       [CURRENT as of YYYY-MM-DD (source) | PROPOSED]
Diagram      [provider · levels drawn · no. of services · no. of steps]
Source       [inventory: where each node and number came from]
System       [design system the page wears, or "neutral sheet"]
Probe        [render.sh output, the 4 lines]
Shots        [paths light/dark, desktop/phone]
My labels    [what you named with no source, for the owner to check]
```

## Origin

The squad's visual grammar, born in a drawing the owner approved. Inventory
before geometry, current/proposed status, audience, the two tests, the real
hierarchy, the draw.io deliverable and `diagram_check.py` come from six
cloud-diagram skills (MIT and Apache-2.0), rewritten; attribution in
`THIRD_PARTY_NOTICES.md`.
