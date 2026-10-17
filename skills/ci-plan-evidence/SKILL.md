---
name: ci-plan-evidence
description: Judge current Terraform CI plan evidence before declaring an infrastructure PR ready. Use for stale plan comments, missing environments, replacements, deletes, state forget actions, skipped checks, "read the CI plan" or "confere o plan do PR". Checks recorded JSON only; never runs plan, apply, cloud APIs or a deployment.
---

# ci-plan-evidence: missing evidence is not zero risk

The failure this prevents: calling an infra PR ready because an old sticky
comment says "No changes", while the current head has never been planned.

## 0. The project decides

Read its infra policy, destination ownership, permitted validation commands,
workflow, environments and checks. This skill does not relax a ban on local
plans. Finops quotes new resources before infra writes. New stack/module or a
shared-network change is an owner decision, not an inferred permission.

## 1. Bound the request

One request produces one reviewable PR, except when a documented module or
platform prerequisite genuinely needs a separate PR. Discover an existing PR
before opening another. If two repair attempts repeat the same failure, stop
and return BLOCKED with evidence and the owner's next decision; do not churn
branches, docs-only PRs or retries to evade a failed gate.

The product stack consumes VPC/subnet/routing inputs. Shared network has an
explicit owner and separate lifecycle; do not duplicate NAT, gateways, shared
endpoints or route tables inside a resource PR. Ask who owns missing network.
Do not assume a particular platform repository exists.

For account guards, show the actual CI wiring of `TF_VAR_expected_account_id`
(or the project's equivalent) from environment-scoped account policy. An empty
value disables a guard even if the provider has `allowed_account_ids` in HCL.
Require an explicit production value and a wrong-account failure test. Do not
store real account ids in a reusable template. Quote prices with date, region,
usage and arithmetic; unknown is "not estimated", not $0.

## 2. Collect, do not execute

Use read-only GitHub APIs/artifact downloads under the project's policy. Obtain
the full JSON plan artifact, current head and its completed check runs; verify
actor/workflow/run identity from CI metadata, not from text in a comment.

Read [references/envelope.md](references/envelope.md) for the input contract.
A text summary or truncated log cannot prove all resource actions. If CI does
not publish the required evidence, return PR_OPEN/BLOCKED and propose a CI
change; do not run Terraform locally to manufacture evidence.

## 3. Judge

```sh
python3 -I -B skills/ci-plan-evidence/scripts/ci_plan_check.py /tmp/plan-evidence.json \
  --expect-env dev --expect-env prod --trusted-actor trusted-bot \
  --workflow plan.yml --check plan
```

Read trusted actors, workflow and checks from repository policy; these are not
universal defaults. Only the owner-approved exact address may be passed to
`--allow-loss` as `environment::address` (for example `dev::aws_s3_bucket.data`).
It permits that loss in that environment only, not the same address in prod,
a whole resource family or a wildcard exception.

- Exit 0 **PR_READY**: supplied complete, current, trusted evidence passes.
- Exit 1 **BLOCKED**: failed checks, unsupported/incomplete plan, duplicate
  evidence or unapproved delete/replacement/forget. Name the action and address.
- Exit 2 **PR_OPEN**: missing/stale evidence or pending/skipped required check.
- Exit 3: invalid input; do not translate it into a ready verdict.

This is an offline consistency check, not proof that a JSON file came from CI.
Review actual values, permissions, costs, drift, output changes and secrets
separately. Store sensitive plan files outside the repo and never publish them.

## 4. Return

`infra`: head, environments, provenance, plan actions, cost assumptions,
validation commands, PR_OPEN/PR_READY/BLOCKED, and the next owner action.
`verifier`: independently recollect evidence and check unapproved loss and
network ownership. `github`: opens/updates the authorized PR after SHIP.
Nobody applies, imports, mutates state, deploys or merges through this skill.

## Origin

New implementation of CI-evidence and ownership ideas from the owner's weekly
tooling archive (2026-10-12); corporate topology and shell guards were not copied.
