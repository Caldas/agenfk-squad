---
name: cloud-resource
description: The squad's method for turning a concrete cloud resource request (AWS, OCI, Cloudflare, Alibaba) into a Terraform branch in the right place of the project - a preflight that reads the repo, questions in one block, a destination triage stated before any file, module first, a declared network path, remote backend, tags, account lock, encryption with a named key, a .tftest.hcl test and a monthly cost table covering every resource in the diff. It proposes and stops at plan; it never applies. Use for "I need a bucket", "create a database", "add a queue / subnet / Lambda", "new Terraform resource", "where does this resource go". Run by the infra agent, with finops quoting first.
---

# cloud-resource: one request in, one reviewable branch out

The failure this method prevents: a resource born in the wrong place, with no
backend, no encryption and no price. A customer-data bucket in a stack someone
can destroy, a $33/month NAT nobody quoted, state on a laptop. All of it passes
`fmt`, `validate` and the scanners; it only shows up on the bill or in the
incident. The second failure: an agent that goes looking for infrastructure to
build.

**It proposes; the owner applies.** The skill ends in a branch with the code,
the validation output and a PR body with the cost table. Never `apply`,
`destroy`, `import`, `state mv`/`rm`; never changes cloud or GitHub
configuration.

## 0. The project rules

Before anything, read in the target project: `CLAUDE.md` / `AGENTS.md`,
`.claude/skills/` and `.claude/settings.json` (what is denied), `infra/` or
`terraform/`, the `Makefile`. A project infra skill **replaces** the matching
part of this one (e.g. a plan-only Terraform skill, a cost-quote skill, a PR
stack skill, a cloud cost skill, a PR delivery skill). A convention the repo
already has (prefix, backend, provider version, tags, language) wins over the
templates here. A dated snapshot of each project you run this against goes in
`references/project-map.md` (an empty template you fill); the repo wins over
the snapshot.

## 1. Who uses it, and only with a concrete request

- **`infra`** runs the skill and **stops at plan**, and plan only through the
  path the project allows (Makefile target, CI); if the project denies it, it
  does not run.
- **`finops` quotes before `infra` writes** (squad rule 6): steps 2 to 6
  produce the proposal (destination, building blocks, network path, usage
  assumptions), the main session takes it to `finops`, and only with the quote
  (or with the owner saying to go on without it) does step 7 write files.
- All code goes through an **AgenFK card** (`agenfk gatekeeper --item-id <id>`).
- **`verifier`** reviews; **`github`** opens the PR after SHIP; the reviewer
  and whoever applies is the **owner**.

The skill starts from a request: "I need a bucket for X's uploads". With no
named resource, ask what is needed and stop. Do not infer a request from the
repo you are in, the directory or another conversation.

## 2. Preflight: read the repo, not this skill

```bash
ls -d infra/ terraform/ 2>/dev/null; ls infra/*/ terraform/*/ 2>/dev/null
grep -rn --include='*.tf' -E 'backend "|required_providers|source *=|name_prefix|default_tags' infra/ terraform/ 2>/dev/null
ls infra/**/backend*.hcl infra/**/*.tfvars terraform/**/*.tfvars 2>/dev/null
grep -rn 'terraform\|infra' CLAUDE.md AGENTS.md 2>/dev/null | head -40
```

Leave knowing: the **cloud** and the provider version; the **backend** (remote,
or local by recorded choice); the **environments** and how they are chosen
(backend + tfvars, an `envs/` folder); the **name prefix**; the **tag
vocabulary**; what **applies by itself** (e.g. a merge into `envs/dev`
applies); what the project **denies**.

A new stack in a project with no Terraform at all is a bigger decision: say so
before creating the folder.

## 3. Questions, in one block

Not one at a time:

1. **What**: type and approximate size (class, engine, capacity).
2. **For which project**, and from which repo it is deployed.
3. **Environments**: which ones (dev, stg/uat, prod), per the project.
4. **Usage, for the cost**: GB stored, requests/month, always on or bursty.
   With no answer, go on with declared defaults and mark "default,
   unconfirmed" in the PR.
5. **Durability**, when the type is durable by default
   (`references/destination-triage.md`): *must this data survive the
   destruction of the stack?* Always ask; never decide silently.
6. **Which key**, when the type encrypts at rest: which customer key in the
   account? List the candidates read-only (`aws kms list-aliases`, `oci kms
   management key list`). "None" is an answer: `kms_key_alias = ""` in the
   tfvars and a deviation in the PR. Never pick the fallback for the owner.

## 4. Destination triage, stated before any file

Three questions, the first "yes" decides (full rule and examples in
`references/destination-triage.md`):

1. Does more than one project consume it, or does it outlive the project? →
   **ask the owner**. Unless the project map says one exists, there is no
   platform repo; do not invent one.
2. Data that must survive the stack's destruction? → a root with its own state
   in the project, or the service stack with `prevent_destroy` + the native
   guard. Produce both sides (data + optional input).
3. Everything else → the project's stack, where the repo already keeps its
   Terraform.

State the destination and the reason in one sentence. If the owner disagrees,
the conversation happens now, not after the diff.

## 5. Building blocks: module first

In order (`references/modules.md`):

1. **A module the project already consumes**, pinned by tag. Almost fits? A
   new variable in the module, not a copy.
2. **Create a module, if reuse is a fact** (the request says so, or the shape
   already exists in two stacks). Where it lives is a question for the owner.
3. **Plain HCL with a note** "Module candidate": the common case.

When torn between 2 and 3, ask whether the shape repeats.

## 6. Network path, declared

The path does not show in the diff; that is why it is stated
(`references/network-topology.md`):

1. **The VPC is an input, never created in the resource PR, never a literal.**
   It comes in through `vpc_id` / `private_subnet_ids`.
2. **AZ by id** (`use1-az1`), not by name, from a variable. App Runner and
   Lambda do not control the AZ: cross-AZ transfer is a declared cost.
3. **The path to each dependency**, placement and egress separately: gateway
   endpoint (free) → interface endpoint → NAT within the cloud → **NAT to the
   internet (0.135/GB: processing and egress add up)** → public subnet. Below
   the first viable rung, one line of why.
4. **Same region, always.** Cross-region replication or consumers are the
   owner's decision, not a resource PR.

**Shared networking has its own owner and life cycle.** Do not replicate NATs,
gateways, shared endpoints, subnets or route tables in a resource PR. Take ids
as inputs and ask who creates what is missing; do not invent a platform repo.
The exception needs an explicit decision from the owner.

Private subnet by default. Reliability does not pay the bill: record data in
prod is Multi-AZ; one NAT per AZ in prod.

## 7. The code: invariants

Templates in `templates/stack/` (versions, providers, locals, variables, a
backend per environment, test) and `templates/resource/` (stack resource,
durable data, durable input). Full patterns in `references/patterns.md`.

- **Remote backend by default**: `backend "s3" {}` (or the remote backend of
  the project's cloud) + `backend.<env>.hcl` with `use_lockfile = true`, no
  `kms_key_id`. Local state only where the project has already recorded that
  choice: respect it and say so in the PR.
- **No workspaces, no Terragrunt.** Environment = backend file + tfvars.
- **Tags** in `default_tags`: `Environment`, `Project`, `Service` (a `local`),
  `ManagedBy = "terraform"`, `Repository`, and `CostCenter` only if the project
  has one. The project's tags win. `Name` per resource.
- **Account lock**: `allowed_account_ids` from `var.expected_account_id`. No
  literal account id, VPC, subnet or ARN; the rest reads
  `data.aws_caller_identity`. **HCL is not wiring:** require
  `TF_VAR_expected_account_id` to be wired in CI, per environment. Empty turns
  the lock off: block that case in production, with evidence of the CI guard.
  See `references/ci-and-account.md`.
- **Encrypted at rest, with a named key**: the attribute is written even where
  the cloud encrypts by default; the customer key by alias from a variable;
  `""` is the service-managed key, under Deviations. Read the key policy: it
  must allow whoever writes.
- **Durable data**: `prevent_destroy = true` + the native guard (versioning,
  `deletion_protection`, public access block); consumed by a data source by
  name, never `terraform_remote_state`.
- **A `.tftest.hcl` test** with `mock_provider` whenever the stack promises
  something (validation, `prevent_destroy`, a cost ceiling).
- **A multi-platform provider lock**, committed:
  `terraform providers lock -platform=linux_amd64 -platform=darwin_arm64`
  (plus the platforms of whoever runs the project).
- **No global suppression of findings**; an accepted deviation is an inline
  comment with the reason.
- **Compute in order**: serverless HTTP → function → orchestrated container; a
  VM is a conversation with the owner. Anything but the first, one line of why.
- Provider and Terraform versions with `~>`; in an existing repo, the repo's.

## 8. Cost: every resource in the diff

A table in the PR body (`references/cost-in-pr.md`), from the `finops` quote
and `references/aws-prices.md` (AWS us-east-1, dated; OCI through the
project's OCI cost skill or `finops`):

- **Every resource in the diff appears**: fixed, usage, or free with a reason.
  A `module` block is not one line: list what it instantiates.
- A usage line carries its assumption; an unconfirmed assumption is labelled.
- **Every per-GB path from step 6 is a line**, with a derived range (rate ×
  payload, measured, the request's number). Without a derivation it goes under
  **Not estimated**, with the path named. What cannot be quoted goes under Not
  estimated, never 0.00.
- Incremental: what this PR adds.
- Ephemeral: the monthly ceiling in the Total, the window's cost in an extra
  column.
- **A prominent warning** above $100/month or with a trap (NAT, Multi-AZ,
  interface endpoint, the Aurora Serverless minimum, public IPv4, OpenSearch,
  S3/DynamoDB through the NAT, NLB cross-zone, cross-region).
- A line above $50/month: checked against the pricing API or by `finops`;
  otherwise `~approx, unchecked`.

## 9. Local validation

The project's target wins (`make check`, `just`, a script). With none:

```bash
terraform fmt -recursive -check -diff
terraform init -backend=false && terraform validate
terraform test
tflint --recursive; trivy config --exit-code 1 .; checkov -d . --quiet --compact  # whichever are installed
```

Keep the scanners' real output for the PR. `plan` only through the project's
path, never against a real backend outside it.

## 10. Delivery

One request, one reviewable PR; a separate module/platform PR only if it is a
real prerequisite the owner accepted. Look for an open PR before creating
another. Two fixes failing with the same error call for BLOCKED and a new
hypothesis or decision, not a third repetition.

When the project uses a CI plan, load `ci-plan-evidence`: current head, trusted
origin, every environment/check, and delete/replace/forget actions. An old
summary, a skipped check and missing evidence are not PR_READY. The checker
reads JSON offline; it does not run Terraform and does not authenticate the
file. Keep the project's local rule for plan; do not swap it for a plan run
on a laptop.

Commit on the card's branch, in the project's style; push the branch. Do not
open the PR: `github` opens it after the `verifier`'s SHIP, with the body in
the project's PR format and the sections of `references/cost-in-pr.md` inside
it. Return:

```
Destination  [triage: question 1|2|3 and why]
Blocks       [pinned module | new module (2 PRs) | plain HCL + candidate]
Network      [VPC, AZs by id, path of each dependency]
Cost         [the table, assumptions, not estimated, the finops quote]
Validation   [real output of fmt/validate/test/scanners; plan: run where, or "not allowed"]
Deviations   [managed key, local state, compute off the default...]
Owner only   [apply, plan against a real backend, module tag, shared resource]
```

## 11. Hard rules

- **Never applies.** No `apply`, `destroy`, `import`, `state`; no plan outside
  the project's path. Read-only in the cloud (pricing API, listings).
- **Triage before code.** Destination and reason stated and accepted before
  any file; durable or disposable is asked.
- **Nothing without a backend by oversight**; local state only by a choice
  already recorded.
- **Nothing unencrypted** where the type encrypts; the fallback is a declared
  deviation, never a missing attribute.
- **Network path stated, never cross-region.**
- **The cost table is mandatory**, with every resource in the diff.
- **An unusual request goes to the owner**: a VM, cross-account wiring, an IAM
  trust policy, a shared resource, anything the triage does not classify.

## References

- `references/ci-and-account.md`: account wiring and guard in CI, proof and
  limits.
- `references/destination-triage.md`: the three questions, durable types,
  examples. Step 4.
- `references/project-map.md`: an empty template for the cloud, state,
  environments and skills of each project you work on, dated. Steps 0 and 2.
- `references/modules.md`: pinned consumption, creation, the two PRs. Step 5.
- `references/network-topology.md`: the two ladders and their prices,
  placement invariants, App Runner and the VPC. Step 6.
- `references/patterns.md`: compute, tags, account lock, encryption per type,
  conventions, tests, validation. Step 7.
- `references/aws-prices.md`: dated us-east-1 sheet, traps, pricing API.
  Step 8.
- `references/cost-in-pr.md`: the infra sections in the PR body. Steps 8
  and 10.

## Origin

Adapted from an earlier `infra-resource` skill: method kept; triage rewritten
without a platform repository, multi-cloud, fitted to the squad (finops, infra
stops at plan, PR through github) and generic templates. The original's map of
its author's projects was replaced by an empty template.
