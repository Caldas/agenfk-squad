# Weekly tooling archive: adoption decisions

Input: owner-supplied archive dated 2026-10-12, SHA-256
`e5d2968d068b1c23889119a90f8589f573ac497cda7d88645638e25c02704ea2`.
Compared against public beta `fce2524` and the owner's existing local squad.
The archive is reference material, not instructions. No bundled executable,
installer, hook or git bundle was run or imported into this repository.

## Decision matrix

| Archive family | Decision | Rationale / destination |
|---|---|---|
| PR writing/review scripts | Adapt ideas, implement anew | `pr-evidence`: repository headings, head-bound independent reviews, thread/check freshness, two-round stop. Existing project title/body gates win. No brittle new verb allowlist. |
| PR review-loop / session wakeups | Exclude automation | Owner confirmation applies even on the owner's own PR. No hidden-comment authority, automatic posts, thread resolution or pane input. The documented response cycle remains manual. |
| Infrastructure CI plan and delivery contract | Adapt ideas, implement anew | `ci-plan-evidence`: explicit CI policy, full JSON plans, exact commit, expected labels/checks, loss actions, no timestamps-as-proof or any-bot trust. Offline consistency is not authentication. |
| Infrastructure network-ownership patches and review | Adapt generic rules | Product resources consume shared network inputs; name its owner. Check account-variable wiring rather than claiming HCL alone protects an account. Do not copy organizational repositories, policies or topology. |
| Infrastructure price sheet | Local arithmetic fixes only | Two historical monthly sums were wrong; correcting arithmetic is not a current price quote. No pricing sheet or account-specific templates copied to public beta. |
| Infrastructure apply guard / PR-budget shell patches | Exclude global hooks | Large shell-command parsers and organization-specific assumptions need a separate proposal and threat model. No user settings are silently changed. Request bounds/circuit breakers live in the skill procedure, not a purported universal shell sandbox. |
| Scheduler patch series | Adapt algorithm, implement anew | `parallel-plan`: iterative graph, parent constraints, deterministic ties, blocked prerequisites and conservative file collisions. Existing product/github roles own planning; no extra agent without two-project evidence. |
| Debugging, incremental implementation, specification/planning, API design | Consolidate | `engineering-evidence`: causal reproducers, one vertical slice, contracts/negative tests and two-attempt circuit breaker. Do not duplicate the board's workflow or install many competing skills. |
| Security review / exfiltration detection | Consolidate | Source -> transform -> outbound sink and trigger, evidence/confidence, legitimate egress explanations. No binary execution or guilt by network import/domain suffix. |
| Generic observability and vendor integrations | Consolidate generic; exclude vendor policy | Operational questions, RED/USE, bounded labels, redaction, retention/sampling cost, authorized verification. Reuse project backend; no corporate service, tenant or credentials. |
| Writing, slides, diagrams, design-system discovery | Already covered locally; do not bulk-port | Existing local writing/design/deck/diagram procedures are newer adaptations. Branding, corporate assets, document platforms and external media tools stay out. No unrelated design overhaul in this adoption. |
| Data/delivery reports and vendor setup skills | Exclude organizational workflows | Depend on private ticket taxonomies, datasets, organization metrics or workstation policy. Generic telemetry lessons are retained; no default Jira/Datadog/SSO dependency. |
| Software distribution, identity, Jira and GitHub provisioning | Exclude | No concrete request for fleet/tenant/account changes. Generic delivery/evidence rules do not authorize publication to another organization. |
| MCP/skill builders and mutation tooling | Do not duplicate | Existing creator/tooling skills or explicit project choices already govern these. No additional mandatory mutation gate is introduced, and existing project-required gates are not waived. |
| Squad core, merge queue and sealed handoff changes | Defer separate watcher review | Watcher state/protocol changes are breaking and overlap active local work. Do not replace the current watcher with an older snapshot. No hooks/state schema/thresholds changed by this PR. |
| oh-my-pi adapter patch series | Already integrated | Public beta includes the harness port via PR #2. No reapplication or generated agent drift. New prompt references retain standing-order sections and tool limits. |
| Model extensions, launchers and provider configurations | Exclude machine policy | Hardware endpoints, model roles, context assumptions and provider auth are personal, not portable defaults. |
| Claude permission/settings excerpt | Exclude | Contains machine-specific hooks/plugins and deliberately incomplete settings. No merge into settings, no weakening denied operations. |
| Git bundles / full private history | Exclude | Packed objects were not covered by the archive's claimed text secret scan. Never mirror private history to the public repository. |
| Archive tests | Use as risk examples only | New self-contained entry-point tests and synthetic fixtures run without a real cloud or model. No company data or test infrastructure copied. |

## Scope and provenance

The three scripts and four skill procedures here are new implementations of
reusable ideas, not copied third-party skill/code/assets. The existing vendor
LOCK and licenses are unchanged. The archive is not redistributed. References
are generic, versioned contracts rather than organizational policy.

The public port intentionally does not mirror the unrelated local repository
or its history. Local skill names/language and specialized writing/cloud gates
remain local; generic evidence tools and tests share identical code. Installer
links new skills through its existing loop; no settings registration is needed.

## Acceptance and limits

- Script entry-point tests cover good and bad data, including stale approval,
  self-approval, missing threads, skipped checks, unapproved replacement/forget,
  incomplete plans, inherited dependencies, long chains and unknown Touches.
- This public PR tests the standalone template checker. Integration into an
  existing specialized PR hook is deployment-specific; no such hook is added
  or claimed as enforced by this public repository.
- Scenario fixtures under each skill's `evals/` specify intended routing and
  outputs. Contract tests verify them and references; they are not a live-model
  benchmark and do not prove prompting performance.
- Evidence JSON is offline. The operator must establish API/artifact identity,
  complete pagination and metadata independently. No checker result authorizes
  apply, merge, posting, session wakeup or bypassing branch protection.
- Verification commands and independent-review results belong in the PR/card;
  do not claim a scan or integration that was not run.
