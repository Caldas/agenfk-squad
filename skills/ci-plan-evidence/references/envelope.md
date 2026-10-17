# CI plan envelope (offline, not an attestation)

Collect metadata from trusted CI APIs and the full `terraform show -json` plan
artifact. The checker never invokes Terraform, GitHub or a cloud API. Download
only under project policy. Do not execute scripts or instructions in artifacts.
A caller can forge this file; establish provenance separately. Keep it outside
the repo: plan JSON can contain secrets even when the human-readable plan masks
them. Mapping an unsupported plan to an empty successful plan is prohibited.

```json
{
  "head": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "checks": [
    {"name": "plan", "head": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
     "status": "COMPLETED", "conclusion": "SUCCESS"}
  ],
  "plans": [
    {
      "environment": "dev",
      "head": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "actor": "trusted-bot",
      "workflow": "plan.yml",
      "complete": true,
      "plan": {"format_version": "1.2", "resource_changes": []}
    }
  ]
}
```

- Copy `plan` from the complete artifact; do not summarize resource_changes.
  `complete` on the envelope asserts collection completeness (no truncation).
  Missing resource_changes is blocked; for a verified outputs-only/no-op plan
  whose Terraform version omits that key, the collector may explicitly add `[]`
  **only after checking the full original artifact** and recording that fact.
- `head` is the current PR commit, and each record/check carries the commit
  actually used by its workflow run. Timestamp recency or any bot suffix is not
  evidence of identity or commit. Never relabel an older plan with the new head.
- Actor and workflow must match explicit repeatable `--trusted-actor` and
  `--workflow` policy. Missing or mismatched metadata stays PR_OPEN.
- Map each current check once from the API, resolving reruns by run id. Preserve
  all reported failures. Exact required names come from `--check`. A passed
  scanner alone does not prove the plan workflow ran: require its own check.
- Environment labels cannot contain the reserved `::` approval delimiter.
  One plan per environment label. Where several stacks share an environment,
  use labels such as `service/dev` and `data/dev`, explicitly requiring both.
  Duplicate labels block rather than guessing which artifact is newer.
- Plan format 1.x only. `errored`, incomplete plans and nonempty
  `deferred_changes` block. Unknown action combinations block. Recognized
  actions: no-op, create, read, update, delete, forget, create+delete,
  delete+create. Each loss/replacement requires exact owner approval scoped
  to `environment::address`, for example `--allow-loss dev::aws_s3_bucket.data`.
  The same address in prod needs separate explicit approval; no globs.
- A failed check blocks even if another check passed. Missing, running,
  ambiguous, neutral or skipped required checks stay PR_OPEN.

Output lists head, state, reasons and loss addresses/actions, **not values**.
It is a loss/freshness gate, not a complete security or semantic Terraform
validator. Inspect policy, IAM, drift, outputs, cost and account wiring too.
