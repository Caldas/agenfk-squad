# Third-party notices

## Cloud diagram skills pack

The diagram rules in `references/inventory-and-drawio.md` and the checks in
`scripts/diagram_check.py` restate rules from six skills, reviewed on
2026-10-01. No text or code is copied; each rule is rewritten and
re-exemplified, and the attribution is kept because the analysis is theirs.

| Source | Licence | Copyright | What derives from it |
|---|---|---|---|
| `vidanov/aws-architecture-diagram-skill` | MIT | (c) 2026 Alexey Vidanov | Checkable layout rules, icon name traps, generic-icon fallback, audience mode |
| `wangchongyu/drawio-architecture-diagrams` | MIT | (c) 2026 Chongyu Wang | Inventory before geometry, the proposed marker, line-style semantics, the hand-edited baseline |
| `alexpov/claude-skill-draw-diagram` | MIT | (c) 2026 Alex Povichuk | Isomorphism and education tests, render-view-fix loop |
| `OpenAEC-Foundation/Draw.io-Claude-Skill-Package` | MIT | (c) 2026 OpenAEC Foundation | Blocking structural stages: well-formed, root and layer cells, unique ids, parent integrity |
| `jgraph/drawio-mcp` | Apache-2.0 | Not stated in its LICENSE; maintained by JGraph | Export with the diagram XML embedded, uncompressed source |
| `awslabs/diagram-as-code` | Apache-2.0 | Amazon.com, Inc. or its affiliates | AWS resource hierarchy, north-south placement |

The MIT text below applies to the four MIT sources. The two Apache-2.0 sources
are used under the Apache License, Version 2.0
(<https://www.apache.org/licenses/LICENSE-2.0>); `awslabs/diagram-as-code`
ships the NOTICE line "Copyright Amazon.com, Inc. or its affiliates. All Rights
Reserved."

## MIT License text

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
