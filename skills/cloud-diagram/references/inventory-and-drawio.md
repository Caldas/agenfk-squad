# Inventory, status, audience and the draw.io deliverable

Detail for the rules in SKILL.md §1 and §8. An architecture diagram is a
claim about a real system: someone opens a security group, pages an on-call
engineer or approves a budget because of it. These rules keep the claim true.

## Inventory before geometry

Before placing a box, write the inventory: each component, the boundary it
sits in, and each connection with its type (synchronous, asynchronous, error,
managed by a third party) and a label of two or three words. **Every node has
a source**, and the source is written in the inventory:

| Source | Example |
|---|---|
| IaC | Terraform module, CloudFormation template, CDK, Pulumi |
| State | `terraform state list`, `terraform show -json` |
| Account, read-only | CLI with a `-ro` profile (`aws ec2 describe-*`), console |
| Written decision | ADR, card, proposal, the owner's request |

Never from memory. Whatever you added or assumed goes in a list and is said
in the answer. A box nobody can tie to a source is an invented fact.

## Status: current or proposed

The stamp has a **Status** cell, separate from **State** (which is about the
application's state: where the data lives, what is stateless):

- `CURRENT as of 2026-10-01 · source: infra/envs/prod`: the running system,
  with the date of the reading and the source.
- `PROPOSED` (or `PROPOSED on 2026-10-10`): the drawing of a decision not yet
  carried out.

Before and after are two sheets on the same page, each with its own Status.
The probe (`render.sh`) and `diagram_check.py` fail a drawing with no status,
and "current" with no date.

## Audience

Ask once when it is not obvious.

| For | The drawing carries |
|---|---|
| Engineering | service name, protocol and port (`HTTPS`, `TCP 5432`), CIDR, instance class, task count |
| Executive | action labels ("stores the order"), no implementation detail, numbered steps `1 2 3` with the same numbers in the text; cost from `finops` alongside |

The grammar (groups, colours, arrows) is the same for both; what is written changes.

## Two tests before drawing

**Isomorphism.** Every box is a real resource and every arrow a real flow.
Remove all the labels: does the shape alone still say something? A fan-out is
one-to-many, a convergence is aggregation, a row is a sequence. A grid of
identical boxes is a list dressed up as a diagram.

**Education.** Does the reader learn something here that a list would not
show? If not, write the list.

## Boundaries follow the real hierarchy

Nest only boundaries that exist (AWS: cloud > account > region > VPC > zone >
subnet). Account with name and id, VPC with its CIDR when the audience is
technical. A boundary drawn for tidiness looks like a security boundary. A
request flow reads left to right; a network view reads top to bottom.

## The editable source is the deliverable

The HTML page with the inline SVG is the editable source of the squad's
standard: the next drawing copies and changes it. When the owner asks for
**draw.io** (`.drawio`):

- draw with the official `mxgraph.aws4` shapes; take the stencil name from a
  checked list, never a guess. A renamed service keeps its old stencil
  (OpenSearch is `elasticsearch_service`, MSK is `managed_streaming_for_kafka`,
  IAM Identity Center is `single_sign_on`); a wrong name renders an empty square;
- save **uncompressed** (the PR diff shows the XML) and export the preview
  with the XML embedded: `drawio -x -f png -e -b 10 -o name.drawio.png name.drawio`;
- every edge attached to a shape at both ends; the legend's sample lines go in
  a container labelled exactly "Legend";
- run the gate:

```bash
python3 -I ~/.claude/skills/cloud-diagram/scripts/diagram_check.py name.drawio
```

| Rule | Fails when |
|---|---|
| `xml`, `structure`, `parent` | malformed XML, DOCTYPE/ENTITY, no root or layer, a parent that is missing or in a loop |
| `compressed` | a page saved as a compressed blob |
| `duplicate-id` | an id repeated on the same page |
| `floating-edge` | an edge with no source or target on the page |
| `lexicon` | a label with a word that reads as AI-written (the `writing` skill's lexicon; `--allow TERM` downgrades it) |
| `status` | no label says CURRENT with a date, or PROPOSED |

Warnings: long label (box > 6 words, edge > 4), box with no label, more than
25 boxes on a page. The script reads the XML; crossing lines and spacing only
show in the rendered image: open the PNG and check.

A tool-generated drawing (diagram-as-code, Python's `diagrams`): fix the
generator and generate again, never edit the output. A drawing someone
adjusted by hand is the baseline: write the new version in another file,
unless asked to replace it.

## Render, look, fix

A drawing that passes the script can still be unreadable. Render it, open the
image, check it against the inventory and the grammar, fix the coordinates,
render again. Two or three rounds is normal; past that, stop and say what is
left.

## Accessibility and duplication

Every diagram has a text equivalent: the `aria-label` that narrates the flow
and the `ol.steps` list. Do not rewrite the whole drawing in prose; one line
with the conclusion is enough, and two full copies drift apart at the next edit.

## Origin

Rules rewritten from six cloud-diagram skills (MIT and Apache-2.0); attribution
in `THIRD_PARTY_NOTICES.md`.
