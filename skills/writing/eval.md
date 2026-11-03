# Self-check

Run this before returning an edit or a tier 2 document. Answer each item pass or
fail. Any fail: fix the draft and run the list again.

For a Detect job, only the last block applies.

For tier 0 and tier 1 output (chat reply, commit message, PR body, email), no
script runs: the memory block at the end of this file runs from memory instead.

## Fidelity (any fail blocks delivery)

1. Did every requirement, decision, number, name, risk and acceptance criterion
   survive unchanged?
2. Did you add no fact, name, number, date, quote, citation or source that was
   not in the source or from the user?
3. Are code, commands, diagrams, links, tables, frontmatter and technical
   identifiers verbatim?
4. For an **Edit** at tier 2: did `fidelity_check.py` exit 0? If a REVIEW line
   appeared, did you read both sentences before acknowledging it, rather than
   passing `--accept-semantic` to make the gate quiet?
4a. For **Write**: did you check the artifact against a coverage list built from
   the sources, instead of running the fidelity script with no real original?
4b. Did you make a final semantic pass over negations, modality, causality and
   decisions? No script covers that.
4c. Did every hedge you cut leave the claim at the same strength? A stacked
   hedge becomes one hedge, never an upgrade to a certainty; no "may" became "will" and no
   fact gained a hedge it did not have. In security, legal, financial, medical
   and incident text, is every qualifier still there?
5. Is the artifact in the language it was already in, with no incidental
   translation?

## Voice

6. Does the edit preserve the writer's distinctive vocabulary, cadence,
   bluntness, humor, uncertainty, digressions and level of polish?
7. Did you leave strong human sentences alone rather than rewriting them for
   consistency?
8. Is the amount of cutting proportional to the actual slop, with no compression
   that stripped character?
9. Is useful edge intact: strong opinions, blunt language, profanity, honest
   admissions, self-interruptions?
10. Is the writer's structure intact, or did you say why you reorganized in
    `What changed`?
11. Would the writer recognize this as their own voice?
11a. Read the densest paragraph aloud, or as close as silence allows. If you
    would not say the sentence to a colleague, rewrite it. The ear catches the
    template the eye skims past.

## Substance

12. Does every sentence carry a fact, number, command, name, decision or risk?
13. Does every generic sentence either pass the portability test or get cut?
14. Does every adjective have a measure attached, or get dropped?
15. Are claims specific rather than smoothed into generic importance?
16. Is the first line the decision, fix, number or command?
17. Is there no opening paragraph announcing the document and no closing
    paragraph restating it?
18. Is each conclusion stated once?
18a. Can any paragraph be deleted without losing information? If yes, delete it.
18b. Could a competent editor cut 15% without losing meaning? If yes, run one
    more compression pass before answering the rest.
18c. Is every heading there for navigation, with content under it a reader
    would look up by that name?
18d. Does the structure follow the content, or did symmetry (equal sections,
    equal paragraphs, triplets) arise because it looks organised? Did a
    conclusion appear because the document needed one, or because models add
    one?
18e. Is every action a verb with a subject, rather than a nominalization chain
    ("the implementation of the optimization")?
18f. For a Write job: did the rules constrain the draft before it existed, and
    did the fix loop rewrite only the flagged sentences rather than the whole
    draft?

## Medium

19. Did you name the relation the reader needs before choosing prose?
20. Is every table a real comparison or mapping, rather than paragraphs hidden in
    cells?
21. Does every diagram carry one message the prose could not carry as cheaply,
    with short specific labels?
22. Is every visual derived only from confirmed source material, with nothing
    invented in a label?
23. Does every visual have a caption or a one-line conclusion, plus alternative
    text?
24. Is the visual free of a prose paragraph that restates it row by row?
25. Is exact technical content (topology, values, permissions, architecture) a
    deterministic diagram, table or code rather than a generated image?
26. Did you avoid building a visual where two or three sentences are clearer?
26a. For an architecture or cloud diagram: did you follow the project's diagram
    skill, when it has one (inventory, current or proposed, editable source,
    render check)?
27. If this is a presentation, did you invoke the presentation skill, when one
    is installed, before planning the slides, and leave the operational document
    as the source of truth?
28. If this is a PR body, does it pass the 30-second test in
    `references/pull-requests.md`, and does it state the outcome rather than
    narrate the work?

## Patterns

29. Are banned words, filler phrases and empty adverbs removed rather than
    replaced with synonyms, except where they are quoted as examples?
30. Are binary contrasts, colon reveals, negative listings, rhetorical setups and
    throat-clearing gone?
31. Are faux-insight setups, shallow -ing analysis, fake-strong verbs, synonym
    cycling and robotic rhythm fixed?
32. Is importance puffery replaced with the plain fact, and weasel attribution
    either given a named source or cut, or flagged to the user when no source
    exists?
33. Is interpretive metadiscourse removed: reader guidance, emphasis markers,
    redundant glossing?
34. Are fake alternatives and unraised objections removed, with any real claim
    inside them stated directly?
35. Was the fake-profound kicker deleted rather than rewritten into a better
    metaphor?
36. Are summary-recap and generic-optimism endings cut, so the text ends on a
    concrete point, takeaway or next action?
37. Is chatbot residue gone, including from the message that accompanies the file?
38. Is every guess either sourced or removed, with no knowledge-limit disclaimer
    left in?

## Mechanical

39. Zero em and en dashes, unless the writer's sample uses them?
40. Straight quotes, sentence-case headings, no emoji?
41. Bold only for a defined term or a warning label?
42. No list where two sentences of prose read better, and no bold-label list?
43. Hyphen before the noun, not after?
44. For tier 2: did `slop_lint.py` exit 0, and does every finding you kept on
    purpose carry one line of justification in your reply or an inline
    `<!-- writing: allow <term> -->`? A declared term is never a deleted fact.
44a. Did you run it again after the last rewrite, with `--profile` when the
    user has a voice profile, and is the ERROR count zero on the final text?
45. No em or en dash glued to the words on either side?

## Output

46. Does an edit return the full edited draft plus a short `What changed`?
47. Does the accompanying message state what changed instead of describing the
    file, with no offer to help further?
48. For a Detect job: does the response name each pattern with a quoted line and
    a short fix, with no rewrite, no score, and no claim about who wrote it, and
    does it say where a visual would beat the prose without building it?

## Tier 0 and tier 1: the memory block

For text that ships straight from the chat, no script runs. This block runs from
memory, in one breath, before sending:

- Would I say this sentence to a colleague out loud? Where I would not, rewrite
  it, not soften it.
- Is the first line the answer, the number or the command?
- Nothing glued by a dash, no emoji, no "Great question!", no closing offer to
  help further.
- Every claim carries a fact, a number or a name. Cut what would survive
  unchanged in another company's mouth.
- Did the default cadence creep back from earlier in the session? Long turns
  after the skill left context are where slop returns; re-read this block.
