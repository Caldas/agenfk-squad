# Pattern catalogue

Every entry: the words that give it away, why it fails, and a before/after pair.
Examples are real infrastructure material where one exists, because a generic
example teaches a generic fix.

Read this the first time you use the skill in a session, or when a paragraph
feels wrong and you cannot name why. Before flagging anything in someone else's
draft, read `false-positives.md`.

## Quick summary: patterns to cut

<!-- vale off -->

Name and fix, with an example in each language where the pattern has a common
pt-BR form. The before/after pairs are in sections A to C below.

| Pattern | Fix |
|---|---|
| Binary contrast: "not just X, it's Y", "não é apenas X, é Y"; negative list: "It's not X. It's not Y. It's Z." | Say Y. Say Z |
| Colon reveal: "The detail that makes it work: a second agent corrects it" | Write the sentence. A colon is for a list, a label and a quote |
| Throat-clearing: "Here's the thing", "Honestly?", "Vale destacar" | Cut it, say the point |
| Faux insight: "the part everyone misses", "o que quase todo mundo erra" | Cut the setup, keep the claim |
| Rhetorical setup: "What if I told you", "Think about it:", a question the next sentence answers | Say the point |
| Announcing: "Let's dive in", "here's what you need to know", "Vamos mergulhar" | Say the point instead |
| Shallow -ing clause at the end: "highlighting", "reflecting", "destacando" | Replace it with the consequence |
| Puffery: "represents a milestone", "is a testament to" | State the fact, the reader judges |
| Name-dropping to impress: "patterns adopted by AWS, Google and Netflix" | Only the citation that says what was adopted, and where |
| Vague source: "experts agree", "studies show", "especialistas concordam" | Name the source or cut it. Never invent one |
| Metadiscourse: "the key point is", "as we can see" | Delete the aside |
| Avoiding is/has: "serves as", "boasts", "conta com" | Use is, has |
| Weak verb: "made a decision", "has the ability to" | decided, can |
| Hidden actor: "mistakes were made", "the decision emerged" | Name who acts. An inanimate thing does not take a human verb |
| Synonym cycling | Repeat the clear word |
| Repeated openings: "She noticed the door. She noticed the lock." | Merge or vary the subject. Do not ban the word |
| Clipped negation at the end: "no drama", "no guesswork", "sem drama" | Write the clause: "without making the user guess" |
| Fake alternative: "a tempting approach would be X, but" | Cut it, state the real constraint |
| Objection nobody raised: "I'm not saying that", "don't get me wrong" | Cut the defence, keep the real claim |
| Sales language: vibrant, cutting-edge, committed to | Cut it |
| Fake-profound kicker | Delete it. Do not rewrite it into a better metaphor |
| Generic ending: "the future looks bright" | Cut the paragraph |
| Stock outlook: "Despite the challenges, X stays strong", a "Future prospects" section | Cut it, or name each risk with an owner and a date |
| False range: "from X to Y" when X and Y do not form a range | Name the items |
| Chatbot residue: "I hope this helps", "Great question!", "You're absolutely right!", "Espero ter ajudado" | Cut it |
| Knowledge disclaimer: "while details are limited", "it is believed that" | Say what the source does not show, or cut it. Never dress a guess as a fact |
| Stacked hedge: "it could potentially be argued that" | One hedge per claim, naming what is uncertain |
| Dramatic fragments: "X. And Y. And Z." | One is emphasis; a row is a tic |

## Quick summary: words to delete on sight

They carry zero information. Delete them, do not look for a synonym.

**en**: delve, leverage, utilize, facilitate, foster, streamline, empower,
seamless, robust, comprehensive, transformative, cutting-edge, game-changer,
holistic, synergy, journey, ecosystem, testament, showcase, pivotal, interplay,
tapestry, multifaceted, meticulous, intricate, paramount, elevate, embark,
supercharge, garner, enhance, crucial, paradigm shift, ever-evolving,
state-of-the-art, groundbreaking, it's worth noting, at the end of the day, at
its core, in order to, truly, basically.

**pt**: vale ressaltar, é importante destacar, de suma importância, no cenário
atual, cada vez mais, mergulhar fundo, desbloquear o potencial, alavancar,
potencializar, robusto, abrangente, escalável, transformador, disruptivo,
revolucionário, holístico, paradigma, empoderar, jornada, ecossistema,
estratégico, sinergia, sem esforço, divisor de águas, em sua essência,
realmente, basicamente.

Some are the precise word in context. "Strategic decision" in a strategy
document is right, and `gate`, `harness`, `key`, `pipeline`, `beacon`
(`sendBeacon`) and `realm` (an authentication realm) are technical terms that
carry weight, which is why they are not on the list. Keeping a flagged word
costs a one-line justification or an inline `<!-- writing: allow <term> -->`,
never silence.

**Empty adverbs.** just, literally, honestly, simply, actually, fundamentally,
inherently, inevitably; só, literalmente, na verdade: cut them when they add
nothing. Keep one when it carries emphasis, uncertainty, contrast or the
writer's spoken rhythm. "It really does ship on Tuesday" stays; "actually,
that's a great question" does not.

<!-- vale on -->

## A. Inflated content

### A1. Importance and legacy puffery

**Watch:** stands as, serves as, is a testament to, a vital/crucial/pivotal role,
underscores its importance, marks a turning point, reflects a broader, symbolizing
its enduring, setting the stage for, indelible mark, deeply rooted, evolving landscape

State the fact. Let the reader decide whether it matters.

Before:
> The CloudTrail rollout marks a pivotal moment in the maturity of the
> platform's security posture and underscores our ongoing commitment to auditability.

After:
> CloudTrail is now delivering in both accounts. Before 2026-08-20 there was no
> API audit trail, so actions taken before that date cannot be attributed.

### A2. Name-dropping to prove importance

**Watch:** independent coverage, leading expert, national media outlets, active
social media presence, trusted by industry leaders

A list of names with no context proves nothing.

Before:
> The approach follows patterns adopted by AWS, Google, Netflix and Spotify.

After:
> The approach follows the AWS Well-Architected guidance on account separation,
> specifically the recommendation to isolate production billing.

### A3. Shallow analysis in an -ing clause

**Watch:** highlighting, underscoring, emphasizing, ensuring, reflecting,
symbolizing, contributing to, fostering, showcasing, encompassing

The clause makes a plain fact sound deeper. Replace it with the consequence.

Before:
> The pipeline now runs checkov on every PR, ensuring a robust security posture
> and reflecting our commitment to shift-left practices.

After:
> The pipeline runs checkov on every PR. A HIGH finding fails the check, so the
> PR cannot merge until the finding is fixed or an exception is declared.

### A4. Sales language

**Watch:** boasts a, vibrant, rich, profound, enhancing its, exemplifies,
commitment to, nestled, in the heart of, groundbreaking, renowned, breathtaking,
must-visit, stunning, seamless, effortless

Before (pt):
> Uma solução robusta, escalável e segura para gerenciamento de dispositivos.

After (pt):
> Intune gerencia os 212 dispositivos atuais. Limite do plano: 15.000.

Three adjectives, zero measures. One number replaces all three.

### A5. Vague sources

**Watch:** industry reports, observers have noted, experts argue, some critics
argue, studies show, it is widely regarded as, several sources

Name the source, or cut the claim. If there is no source, ask. Never invent one.

Before:
> Industry reports suggest that most organizations struggle with Terraform state
> management at scale.

After:
> Three of our nine stacks still keep state locally, which is why `terraform plan`
> cannot run in CI for them (see the FinOps report, 2026-08-11).

### A7. Generic framing

**Watch:** in today's rapidly evolving, in an increasingly complex, in the
modern era, the landscape of, in this document we will, last but not least, no
cenário atual, nos dias atuais, em um mundo cada vez mais, nesse contexto, por
fim mas não menos importante

The opener could sit on top of any document in any company. The reader learns
nothing until the second sentence.

Before:
> In today's rapidly evolving cloud landscape, observability is more important
> than ever. In this document, we will explore our approach.

After:
> Observability goes to Datadog. Log Analytics stays for Sentinel only.

### A6. Formulaic challenges and outlook sections

**Watch:** Despite its... faces several challenges, Despite these challenges,
Challenges and Legacy, Future Outlook, Next Steps as a stock heading with no owner

A stock section repeats vague claims instead of adding facts. Either name the
risk with its owner and date, or delete the section.

Before:
> Despite these challenges, with continued investment and cross-team
> collaboration, the platform is well positioned for future growth.

After:
> Two blockers remain. `DD_APP_KEY` is not in CI (owner: Ana, no date yet).
> Three stacks have local-only state, which blocks plan in CI.

## B. Sentence shapes

### B1. Binary contrast

**Watch:** not just X but Y, it's not X, it's Y, the question isn't X, it's Y,
Not a X. Not a Y. A Z., não é apenas X, é Y, não se trata de X, mas de Y

The contrast is manufactured. State Y. The list form ("Not a X. Not a Y. A Z.")
gets the same fix: say Z.

Before:
> This isn't just a cost optimization, it's a fundamental shift in how we manage
> identity.

After:
> Removing the 43 unused E5 licenses saves USD 2,451/month. It also moves license
> assignment from per-user to group-based.

### B2. Colon reveal

A noun phrase, a colon, then a lowercase dramatic reveal. Colons are for lists,
labels and quotes, not suspense.

Before (pt):
> O problema real não era o Terraform. Era outra coisa: o state estava em drift.

After (pt):
> O state estava em drift desde o apply manual de 12/08. O Terraform estava correto.

Suspense costs the reader a sentence. The date is the information.

### B3. Forced groups of three

Three items because three sounds complete. Keep the one that carries a measure.

Before:
> The rollout was fast, safe, and well documented.

After:
> Rollout completed at 14:32 UTC. Zero incidents, zero rollbacks.

### B4. False from X to Y ranges

X and Y do not form a real range; they are just two items with a preposition.

Before:
> The platform covers everything from identity to observability, from cost
> control to compliance.

After:
> The platform covers three areas: Entra group provisioning, Datadog monitors as
> Terraform, and the FinOps report.

### B5. Synonym cycling

If the clear word is right, repeat it. Do not rotate terms for style.

Before:
> The agent reviews the draft. The assistant scores the piece. The tool suggests
> fixes.

After:
> The agent reviews the draft, scores it, and suggests fixes.

### B6. Repeated sentence openings

Fix the repeated pattern, not the repeated word. The result may still start with
the same subject.

Before:
> The workflow reads the diff. The workflow calls the model. The workflow posts
> the comment.

After:
> The workflow reads the diff, calls the model, and posts the comment. The model
> only writes text; the workflow does the posting.

### B7. Passive voice and missing subjects

Say who acts.

Before:
> No configuration file is needed. The results are preserved automatically.

After:
> You do not need a configuration file. The runner keeps the results for 90 days.

### B8. Avoiding is and has

**Watch:** serves as a, stands as a, represents a, boasts a, features a, offers a

Before:
> The repository serves as the single source of truth for GitHub configuration
> and features three separate stacks.

After:
> The repository is the source of truth for GitHub configuration. It has three
> stacks: repos, teams, and rulesets.

### B9. Weak verb phrases

"made a decision" becomes "decided". "has the ability to" becomes "can". "provides
support for" becomes "supports". "is responsible for handling" becomes "handles".

### B10. Nominalization chains

**Watch:** the implementation of, the optimization of, the alignment of, the
enablement of, utilization, facilitation, transformation, a implementação da,
a otimização da, o alinhamento das, a habilitação da

One abstract noun per sentence is ordinary technical prose: "the implementation
reads the state once". Two or more in one sentence hide who acts and what
changes. Find the verb and its subject.

Before:
> The implementation of the optimization requires the alignment of the
> configuration across environments.

After:
> Before the cache can go live, staging and production must use the same
> `cache_ttl`. Today staging has 300 s and production 60 s.

### B11. Clipped negative endings

A clause compressed into a two-word negative after the fact: "no guessing",
"no drama", "no exceptions".

Before:
> The options come from the selected item, no guessing.

After:
> The options come from the selected item; the user never has to guess.

The caption is not a sentence. Write the clause.

## C. Framing tics

### C1. Throat-clearing openers

**Watch:** Here's the thing, Here's what I mean, Let me be clear, I'll be honest,
The uncomfortable truth is, Honestly?, Look, Real talk, Vale destacar, É
importante ressaltar, Cabe destacar

Cut it and state the point. Note the casual register counts too: "one thing that
bit me hard, so pay attention" is the same pattern in a t-shirt.

Before (pt):
> Vale ressaltar que essa abordagem nos permite alavancar o investimento já feito
> em Datadog e desbloquear novas capacidades de correlação.

After (pt):
> Reusa o contrato Datadog atual. Adiciona correlação de logs com traces.

### C2. Faux-insight setups

**Watch:** this is the part most people skip, what most people get wrong, here's
what nobody tells you, the part everyone misses

These flatter the writer as the lone expert. Cut the setup and let the claim stand.

Before:
> The part everyone misses: AWS only evaluates `aud` and `sub` in an OIDC trust
> policy.

After:
> AWS only evaluates `aud` and `sub` (plus `amr`, `oaud`, `email`) in an OIDC
> trust policy. A condition on `job_workflow_ref` never matches, and the denial
> looks identical to a missing role.

### C3. Announcing the next point

**Watch:** let's dive in, let's explore, let's break this down, here's what you
need to know, now let's look at, without further ado, quick note, heads up

Before:
> Let's dive into how the gatekeeper works. Here's what you need to know.

After:
> The gatekeeper is a PreToolUse hook. It blocks Edit, Write and NotebookEdit
> when no AgEnFK task is in an active working step.

### C4. Interpretive metadiscourse

**Watch:** the key point is, as you can see, this distinction matters, that last
part matters more than it sounds, in other words (redundant), it is worth
understanding that

Lines that step outside the subject to tell the reader what to notice. If the
point is clear, delete the aside. Otherwise replace it with the supporting fact.

### C5. Rhetorical questions

**Watch:** What if I told you, Think about it:, Plot twist:, a question the next
sentence answers

The question exists only to be answered in the next sentence.

Before:
> Why does this matter? Because every minute of downtime costs us customer trust.

After:
> Downtime SLA is 99.9%. The incident consumed 38% of the monthly error budget.

### C6. Answering objections nobody raised

**Watch:** this isn't really about, I'm not saying, I'm not arguing that, to be
clear, don't get me wrong, this is not to say, you could frame it differently but

Before:
> This isn't mainly about prompt length, and I'm not arguing that documentation
> doesn't matter. You could categorize the problem another way, but the issue is
> whether the agent can use the instruction when it acts.

After:
> The issue is whether the agent can use the instruction when it acts.

Remove only the unsupported defence. Keep an objection when the text names its
source or answers it in full. A direct claim ("the API is not thread-safe") is
not this pattern.

### C7. Rejecting fake alternatives

**Watch:** a tempting approach would be, one might be tempted to, an obvious
approach would be, it would be easy to just, some would suggest

Usually a leftover from an earlier draft. Remove the option nobody would try and
state the real constraint.

Before:
> Session tokens rotate every 24 hours. A tempting approach would be to rotate
> them by restarting the auth service on a cron job, but that would drop every
> active session. Rotation happens in place.

After:
> Session tokens rotate every 24 hours, in place, and clients refresh
> transparently.

One rejected option can be legitimate in a design document. Several short
unrelated rejections are the tell.

### C8. Pretending to reveal a deeper truth

**Watch:** the real question is, at its core, in reality, what really matters,
fundamentally, the deeper issue, the heart of the matter, em sua essência

Before:
> The real question is whether teams can adapt. At its core, what really matters
> is organizational readiness.

After:
> Whether teams adapt depends on whether they change their review habits. Today
> two of five repos have required checks disabled.

### C10. Transition stacking

**Watch:** furthermore, moreover, additionally, in addition, consequently, on
the other hand, importantly, that being said, além disso, ademais, outrossim,
por outro lado, consequentemente, nesse sentido, dessa forma

One of these is a connective. Four in a page is a template: the writer is
labelling each paragraph as "more" instead of letting the content relate. Cut
the ones that do not name a real relation. "Because", "so", "however" and "as a
result" state one and stay.

Before:
> The runner reads the diff. Furthermore, it calls the model. Moreover, the
> model writes the comment. Additionally, the runner posts it.

After:
> The runner reads the diff, calls the model and posts the comment the model
> wrote. The model never posts.

### C9. Formulaic sayings

**Watch:** X is the Y of Z, X becomes a trap, X is not a tool but a mirror, the
language of, the currency of, the architecture of

Before:
> Observability is the currency of trust in a distributed system.

After:
> Without traces you cannot tell whether the p95 came from Gemini or from the
> watchdog re-running the turn.

## D. Endings

### D1. Fake-profound kicker

Delete the final deep line. Do not rewrite it into a better metaphor. Do not
preserve its rhythm. End on the clearest concrete sentence already in the draft.
If the ending needs closure, add a plain takeaway or a next action with an owner.

### D2. Summary-recap ending

**Watch:** in conclusion, ultimately, overall, in summary, por fim, em suma

Before:
> In summary, this RFC proposes a phased migration that balances risk and speed
> while keeping the team aligned. I hope this gives a clear picture. Let me know
> if you have any questions.

After:
> (deleted)

The document already said all of this. The last paragraph is the reader's cue to
stop reading; give them the cue by stopping.

### D3. Generic positive ending

**Watch:** the future looks bright, exciting times ahead, a step in the right
direction, well positioned for growth, continues to thrive

Cut the paragraph. End on the last concrete fact. If the source states real
plans, use those instead.

## E. Filler and hedging

### E1. Filler phrases

| Before | After |
|---|---|
| in order to achieve this goal | to achieve this |
| due to the fact that | because |
| at this point in time | now |
| in the event that you need help | if you need help |
| has the ability to process | can process |
| it is important to note that the data shows | the data shows |
| com o objetivo de | para |
| no que diz respeito a | sobre |

### E2. Preamble

Before (pt):
> Neste documento, vamos explorar a arquitetura proposta para o novo ambiente de
> observabilidade, cobrindo os principais componentes e as decisões tomadas.

After (pt):
> Observabilidade vai para Datadog. Log Analytics fica só para Sentinel.

The first version tells the reader a document exists. The second tells them the
decision.

### E3. Stacked qualifiers

**Watch:** to be fair, it's also possible, could potentially, might arguably, in
some cases it may, this is an inference

Before:
> It could potentially be argued that, in some scenarios, this might possibly
> lead to increased latency.

After:
> p95 latency rises from 120 ms to 180 ms while the cache is cold, for the first
> 5 minutes after a deploy.

Four hedges hid one measurable condition. Name the condition; drop the hedges.
One hedge per claim, only when the uncertainty is real, and say what is uncertain.

### E4. Unsupported certainty

**Watch:** undoubtedly, certainly, undeniably, unquestionably, clearly,
obviously, there is no doubt, it is clear that, sem dúvida, inegavelmente,
certamente, é evidente que, não há dúvida

The adverb replaces the evidence. If the evidence exists, state it and the
adverb becomes redundant; if it does not, the sentence is a guess wearing a
uniform. The fix runs one way only: show the evidence or keep the hedge. Never
strengthen the claim further, and never turn a real "may" into a certainty
because it reads cleaner.

Before:
> This change will undoubtedly eliminate deployment failures.

After:
> In the last 30 deployments the failure mode from the old pipeline did not
> recur. The next release is the first one with database migrations, so the
> result does not cover that case yet.

### E5. Empty adverbs

**Watch:** just, literally, honestly, simply, actually, truly, fundamentally,
importantly, crucially, inherently, inevitably

Cut an adverb that adds nothing. Keep one that carries emphasis, uncertainty,
contrast or the writer's spoken rhythm.

Before:
> The migration is literally just moving the state, essentially.

After:
> The migration moves the state. Nothing else changes.

## F. Chatbot residue

### F1. Chatbot text left in the answer

**Watch:** I hope this helps, Of course!, Certainly!, Great question!, You're
absolutely right, Would you like me to, Want me to, Should I continue, let me
know if, here is a

### F2. Overly agreeable tone

Before:
> Great question! You're absolutely right that this is a complex topic.

After:
> The economic factors you mentioned are relevant here.

### F3. Knowledge-limit disclaimers and gap-filling

**Watch:** as of my last training update, while specific details are limited,
based on available information, not publicly available, maintains a low profile,
likely began, it is believed that

State what the source does not show, or cut the sentence. Never present a guess
as a fact.

Before:
> While the exact authorship is not extensively documented, it appears the stack
> was created sometime in early 2026.

After:
> Authorship is not recoverable. CloudTrail only retains events from 2026-08-20,
> and the stack predates that.

### F4. Chat message accompanying a file

Before:
> Here's the runbook you asked for! I've structured it with clear preconditions,
> numbered steps, and a rollback section. Let me know if you'd like any changes.

After:
> Runbook in `docs/runbooks/intune-compliance-rollout.md`. Step 6 needs
> `DeviceManagementConfiguration.ReadWrite.All`; you hold Global Administrator,
> so it is covered.

The first version describes the file's shape. The second tells the reader the one
thing they need before opening it.

## G. Formatting

### G1. Em and en dashes

The final text contains no `—` or `–` unless the writer's own sample uses them.
Replace with a period, comma, colon or parentheses, or rewrite the sentence. Also
catch spaced dashes and `--` used as a dash. Sweep for both marks before
returning.

Before:
> The rollout was clean, no incidents, no rollbacks, and the team was thrilled.
> (original used em dashes around the middle clause)

After:
> Rollout completed at 14:32 UTC. Zero incidents, zero rollbacks.

The dashes stage a reveal. "Thrilled" is not a fact about the rollout.

### G2. Bold as emphasis

Before (pt):
> É **fundamental** que o backup seja **validado** antes de **qualquer** alteração.

After (pt):
> Valide o backup antes de alterar. Comando de validação no passo 3.

Bold mid-sentence is the writer shouting because the sentence has no consequence
attached. Attaching the consequence removes the need to shout.

### G3. Lists with bold mini-headings

Before:
> - **User experience:** the interface has been significantly improved.
> - **Performance:** performance has been enhanced through optimized algorithms.
> - **Security:** security has been strengthened with end-to-end encryption.

After:
> The update redraws the settings panel, cuts cold start from 4.1 s to 0.9 s, and
> encrypts the local cache.

### G4. Title case in headings

`## Strategic Negotiations And Global Partnerships` becomes
`## Strategic negotiations and global partnerships`. Proper nouns keep their case.

### G5. Emoji

None, in headings or anywhere, unless a house convention requires one.

### G6. Curly quotation marks

Replace `“ ” ‘ ’` with straight quotes unless the target format wants curly.

### G7. Hyphenated pairs

**Watch:** third-party, cross-functional, client-facing, data-driven,
decision-making, well-known, high-quality, real-time, long-term, end-to-end

Keep the hyphen before a noun (`a high-quality report`), drop it after (`the
report is high quality`).

### G8. Dramatic fragments and robotic rhythm

One short sentence adds emphasis. A row of them is a tic. Avoid repeated sentence
shapes and identical paragraph structures.

Before:
> Then the gate landed. No exceptions. No overrides. No way around it.

After:
> The gate landed with no override path, so a HIGH finding now blocks the merge
> until it is fixed or an exception is declared in the PR body.

### G9. A heading restated by its first sentence

Before:
> ## Performance
>
> Speed matters.
>
> When a page takes over 3 s, users leave.

After:
> ## Performance
>
> When a page takes over 3 s, users leave.

### G10. Writing about the previous version

Documentation describes current behaviour. The previous version belongs in a
changelog, release note or migration guide.

Before:
> This function was added to replace the previous approach of iterating through
> all items, which caused O(n^2) performance.

After:
> This function uses a hash map for O(1) lookups.
