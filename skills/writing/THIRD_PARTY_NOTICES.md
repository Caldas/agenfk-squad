# Third-party notices

This skill merges material from several writing sources. Their licences and
attributions are kept here. The rest of the skill is covered by the
repository's licence (see `LICENSE` and `NOTICE` at the root).

## humanizer

MIT License. Copyright (c) 2025 Siqi Chen. Distributed at
`blader/humanizer` (licence read from its `LICENSE` on 2026-11-03).

The pattern catalogue in `references/patterns.md`, the false-positive
discipline in `references/false-positives.md` and part of the English lexicon
in `scripts/slop_lint.py` derive from it.

```
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
```

## Wikipedia: Signs of AI writing

The humanizer patterns are themselves based on
<https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing>, maintained by
WikiProject AI Cleanup. Wikipedia text is available under CC BY-SA 4.0. The
patterns here are restated and re-exemplified rather than copied; the
attribution is kept because the analysis is theirs.

## no-ai-slop

MIT License. Copyright (c) 2026 Peter Yang. Distributed at
`petergyang/no-ai-slop` (licence read from its `LICENSE` on 2026-11-03). Voice
preservation, the minimum-effective-edit principle, the portability test, the
Detect job and part of the lexicon in `scripts/slop_lint.py` derive from it; the
rules are restated in this skill's own words. The MIT permission notice in the
humanizer section above applies to this material too, with this copyright line.

## claudekit `brand`

From `mrgoonie/claudekit-skills`. No licence file was found at that
repository's root on 2026-11-03, so no licence is claimed here. Only the idea of
the brand-voice axes in `references/voice-profile.md` is taken; the text is
written in this skill's own words and no file or passage is copied.

## caveman

Apache License, Version 2.0 (<https://www.apache.org/licenses/LICENSE-2.0>).
Copyright 2026 Julius Brussee. Distributed at `JuliusBrussee/caveman`.

The lean mode, the commit message rules and the Compress job in
`references/lean.md`, and the evidence discipline of the Detect job in
`SKILL.md`, restate rules from its `caveman`, `caveman-commit`,
`caveman-compress` and `caveman-evidence-review` skills. Changes: the
compressor that sends the file to a model provider is replaced by a local
rewrite gated by `scripts/fidelity_check.py`; the hosted-service specifics of
the evidence review are dropped and only its reporting rules are kept.

## The original authors' writing skills

The sentence test, the measure table, the document shapes, the pt-BR lexicon,
`slop_lint.py` and `fidelity_check.py` come from two internal writing skills
(`plain-technical-writing` and `human-friendly-docs`) contributed by this
repository's author; they are not third-party material and are listed here for
provenance.

## Cloud diagram rules

The diagram rules that derived from cloud diagram skills live in the
`cloud-diagram` skill, together with their attribution.
