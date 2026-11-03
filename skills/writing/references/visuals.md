# Tables, diagrams, figures and decks

The goal is not less text. It is a reader who understands faster. Sometimes that
is a five-row table, sometimes a diagram, sometimes three well-written sentences.
Let the information and the task pick the medium, not the format the model
reaches for by default.

## Order of precedence

Medium selection sits fourth. It never overrides what is above it.

1. Preserve facts, requirements, decisions, risks, numbers, commands, code and
   identifiers.
2. Obey the format and language the user asked for.
3. Keep the artifact searchable, accessible and fit for its function.
4. Choose the medium that communicates with least effort.
5. Apply style, concision and slop removal.

This order is what stops a table from hiding load-bearing reasoning, a figure
from inventing an architecture, and a deck from replacing an executable runbook.

## Tables

Use one when there are at least three comparable items and two or more shared
attributes, or for an exact mapping: permissions, costs, states, owners, dates,
repeated acceptance criteria, decision matrices.

A good table has two to six columns, concrete headers, and short cells. Long
detail goes below the table, not inside it. Rows must actually be comparable
across the columns. Numbers and technical terms stay exactly as given.

Do not use a table when there is one item, when the information depends on
continuous reasoning, when a cell would need several paragraphs, when linear
reading is part of the meaning, or when the table only decorates the page.

Long prose is not compressed into cells. The table has to reveal a comparison or
a mapping that already exists in the content. If it does not, you are hiding
paragraphs in a grid.

## Diagrams

Use one when the relation matters more than the individual elements: three or
more connected components, three or more dependent steps, branching, states,
ownership, data flow, or a sequence with returns and exceptions.

| Relation | Diagram |
|---|---|
| Components and connections | Architecture or top-down flowchart |
| Calls between services | Sequence diagram |
| States and transitions | State diagram |
| Entities and cardinality | ERD |
| Dependencies | Dependency graph |
| Branching decision | Decision tree |
| Change over time | Timeline or Gantt |
| Hierarchy | Tree, mind map or org chart |

A diagram carries one main message. Labels are short and specific. Show direction
and boundaries when they matter. Avoid crossed lines and node sprawl. It must fit
the artifact's normal width. Add a legend only when the symbols are not obvious.
Always follow it with a short line stating the conclusion the reader should take
from it. Base it only on confirmed facts and relations.

For versioned documentation prefer Mermaid when it supports the diagram type, so
the diagram stays editable and reviewable in a pull request. For executive
material or a deck, a richer visual tool is fine as long as the content stays
verifiable.

Do not draw a two-element chain, an obvious relation, or a list a table
communicates better. A large empty diagram is another kind of slop.

## Architecture and cloud diagrams

An architecture or cloud diagram is a claim about a real system: inventory
before geometry, current-or-proposed status, editable source and the render
check. Those rules and their checker live in the `cloud-diagram`
skill. This file keeps only the choice of medium above.

## Figures

Use one when appearance, position or visual recognition is needed to understand
or perform the task: where an option sits in a console, which physical port,
a layout, a before/after, or a conceptual view for a non-technical audience.

A figure needs a caption stating what it demonstrates, annotations or arrows
where they help, enough resolution to read, and alternative text or an equivalent
description. Say when it is illustrative and does not represent exact values or
topology. Names, numbers and labels must match the source text.

**Never use a generated image for exact technical content**: topology, data,
values, permissions, architecture. Those need a deterministic diagram, a table or
code. Generated images are for conceptual illustration, mockups, characters and
narrative support.

## Slide decks

Any request for slides, a presentation, a deck, PowerPoint, training, a workshop,
an executive briefing, a readout, or anything meant to be projected invokes a
presentation skill, when one is installed, before the slides are planned or written. This skill owns
prose and fidelity; the presentation skill owns structure, layout, pacing, visual hierarchy
and rendering. If it is unavailable, say so and use another workflow only with
the user's approval.

Do not convert a README, ADR, RFC, runbook, spec, ticket, email or chat message
into slides unless the user asked for a deck or the deck is explicitly a
companion deliverable. A deck is the wrong container for content that has to be
executed, searched, reviewed line by line or kept next to the code.

For a long report with an executive audience, offer a companion deck. The report
stays the complete source; the deck carries decision, impact, risk and next
steps.

## Accessibility and duplication

Every visual needs a text equivalent: alternative text, a caption, or the
surrounding sentence that states its conclusion. A reader using a screen reader,
a plain-text diff or a terminal must still get the point.

Do not restate the whole visual in prose. One short line with the conclusion is
right; a paragraph that walks every row is duplication, and the two copies will
drift apart on the next edit.

## What no script checks here

Whether a table hides paragraphs, whether a diagram carries a useful relation,
and whether a figure needs a caption are judgement calls. `slop_lint.py` catches
the mechanical symptoms only: `list-over-prose`, `long-bullet-run`,
`bold-label-list`. The rest is the `eval.md` pass.
