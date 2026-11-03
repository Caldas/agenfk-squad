# Patterns: what every generated resource complies with

The project's CLAUDE.md, its infra skill and what the repo already does win
over this page. It applies to a new stack and to whatever the project has not
decided. Examples are AWS; on OCI, Alibaba and Cloudflare the principle is the
same and the attribute is the provider's (read it in
`terraform providers schema -json`, do not generalise from the neighbour).

## Compute priority

A request for "a service": take the first one that fits.

1. **Managed serverless HTTP** (App Runner; Container Instances on OCI;
   Workers on Cloudflare). The default.
2. **Function** (Lambda, OCI Functions, Function Compute) for events and
   schedules.
3. **Orchestrated container** (ECS Fargate) only when 1 does not fit: sidecar,
   non-HTTP protocol, long-lived connection, its own networking.
4. A VM (EC2, Compute) is not on the list: it is a conversation with the owner.

Choosing anything other than 1 needs a one-line justification in the PR. It is
not a formality: Fargate brings an ALB and often a NAT, some $50/month fixed
before the first request. App Runner egresses to the internet by default; with
a VPC connector *everything* egresses through the VPC, and then calling an
external API needs a NAT (see `network-topology.md`).

## Tags

On the provider's `default_tags`, so no resource escapes (the stack's
`locals.tf`):

| Tag | Value |
|---|---|
| `Environment` | `var.environment` |
| `Project` | the project |
| `Service` | a `local`, one value per stack; never a tfvar |
| `ManagedBy` | `"terraform"` |
| `Repository` | `<owner>/<repo>`: makes the expensive Cost Explorer line actionable |
| `CostCenter` | only when the project has one; never invent it |

`Name` never goes in `default_tags`: it is per resource. A resource that
`default_tags` does not reach gets an explicit `tags = local.tags`. The set is
a floor, not a ceiling; if the project has its own tag vocabulary, it wins. On
OCI they are `freeform_tags`/`defined_tags`; on Alibaba, `tags`; Cloudflare
barely has any.

## Account lock

A prod credential with `-var-file=dev.tfvars` creates real resources in the
wrong account. The provider refuses first: `allowed_account_ids` fed by
`var.expected_account_id` (`providers.tf`). The account id only enters the code
through that variable, in `<env>.tfvars`; the rest reads
`data.aws_caller_identity`. No literal account id in a `.tf`.

## Naming

- Terraform identifiers in `snake_case`.
- Resource names with the project prefix (`local.name_prefix`). Read the
  prefix the repo already uses: in an account with IAM policies scoped by ARN
  pattern, a name outside the pattern passes plan and fails apply with
  `AccessDenied`.

## Security

- No `0.0.0.0/0` in a security group, except the ingress of a genuinely public
  load balancer.
- Public access block on every bucket, except a bucket that exists to serve
  public content, and the PR says so.
- Secrets never in `.tf` or `.tfvars`: Secrets Manager / SSM / Vault, by ARN.
- IAM policies with specific resources; `Resource = "*"` needs a
  justification.

## Encryption at rest, with a named key

Every type that encrypts at rest is generated encrypted, with the attribute
written even where the cloud already encrypts by default: an attribute absent
from the diff does not say whether the default was accepted or nobody thought
about it.

The key, in this order:

1. **A customer key that already exists in the account**, read by alias
   (`data.aws_kms_key` on `alias/<name>`), with the alias coming from
   `var.kms_key_alias` with no default: the choice is visible in
   `<env>.tfvars`. A literal key ARN in the code fails review.
2. **No customer key** → the service-managed one (`aws/s3`, `aws/sqs`...), with
   alias `""` in the tfvars, and the PR names it under **Deviations**.

**The key policy is where it breaks.** Reading the key by alias gives an ARN;
it grants nobody anything. An SSE-KMS bucket whose key policy forgets the
writer applies cleanly and denies every `PutObject` in production; a log group
without `logs.<region>.amazonaws.com` in the policy fails at apply. Read the
policy and name in the PR the principals it must allow.

**A new key** is a decision of its own, quoted (`aws-prices.md`), and for
durable data it lives with the data, because destroying the key destroys the
data. A key created in the same stack is referenced as
`aws_kms_key.<name>.arn`; pointing the data source at an alias the same apply
creates fails on the first plan.

**Encryption costs.** SSE-S3 is free; `aws:kms` bills one KMS request per
operation, and `bucket_key_enabled = true` cuts that to almost nothing.
DynamoDB with a customer-managed key also bills on the read and write path. A
line in the cost table, with the request estimate.

| Resource | Required attribute |
|---|---|
| S3 bucket | `aws_s3_bucket_server_side_encryption_configuration` with `sse_algorithm` and `kms_master_key_id`; `bucket_key_enabled` |
| RDS / Aurora | `storage_encrypted = true`, `kms_key_id` |
| EBS / EFS volume | `encrypted = true`, `kms_key_id` |
| DynamoDB table | `server_side_encryption { enabled = true, kms_key_arn }` |
| SQS queue | `kms_master_key_id`, or `sqs_managed_sse_enabled = true` |
| SNS topic | `kms_master_key_id` |
| ECR | `encryption_configuration { encryption_type = "KMS", kms_key }` |
| Log group | `kms_key_id`, customer key only |
| Secret | `kms_key_id` |
| Backup vault | `kms_key_arn` |

Scanners and the optional key: the ternary `alias == "" ? null : ...` silences
"customer key expected" findings even when it resolves to `null`. In the
fallback, answer inline (`#trivy:ignore:<id>` or `#checkov:skip=<id>:<reason>`)
with the reason. A green scan without that comment is a hidden finding, not an
answered one.

## Availability

Record data in prod is Multi-AZ; a test environment may be single-AZ. Cross-AZ
transfer is never a reason to remove redundancy: standby replication is not
billed; the cost of Multi-AZ is double instance and double storage. Both go in
the cost table.

## Terraform conventions

- **Remote backend by default in a new stack:** `backend "s3" {}` (or the
  project cloud's remote backend) + `backend.<env>.hcl` with
  `use_lockfile = true`. Local state only when the project has already
  recorded that choice (see `project-map.md`); respect it and say so in the PR.
  Never generate a new stack without a backend by oversight.
- **No `kms_key_id` in the backend file:** the state bucket encrypts by
  default.
- **No workspaces, no Terragrunt.** The environment comes from
  `backend.<env>.hcl` + `<env>.tfvars` at init/plan; `terraform.workspace`
  does not appear in the code.
- **`~>` on the Terraform and provider versions** (pins the major);
  reproducibility comes from the committed `.terraform.lock.hcl`, with every
  platform of whoever runs it: `terraform providers lock -platform=linux_amd64
  -platform=darwin_arm64` (add the ones the project uses).
- **Modules pinned by tag**, never a branch. Build artifacts pinned in the
  tfvars (zip version, image tag), never `latest`.
- **No `modules/` until a second stack needs the same block** (`modules.md`).
- Every `variable` and every `output` has a `description`.

## The stack's test is part of the stack

`terraform test` with a mocked provider (`mock_provider`) runs with no
credential. A stack that promises something (variable validation,
`prevent_destroy`, a cost ceiling, immutability) has `tests/*.tftest.hcl`
asserting the promise, and changing the promise changes the test in the same
PR. Example: `templates/stack/tests/variables.tftest.hcl`.

## A policy finding is answered, never suppressed

No `.checkovignore`, no global suppression. An accepted deviation gets an
inline comment with the cost or the compensating control. A global
suppression is silently inherited by the next stack; an inline one has to be
defended every time.

## A plan that destroys is a plan that stops

A plan with `delete` or `replace` does not go ahead without the owner. Say in
the PR what is replaced and why.

## No account literal in the code

Account id, VPC id, subnet id, zone name and ARN come in by variable or by a
data source filtered by tag. If the stack does not install into an empty
account, something is hard-coded.

## Local validation

**The project's `Makefile` (or `justfile`, script) wins.** With no target of
its own:

```bash
terraform fmt -recursive -check -diff
terraform init -backend=false && terraform validate
terraform test
tflint --recursive              # if installed
trivy config --exit-code 1 .    # if installed
checkov -d . --quiet --compact  # if installed
```

Attach the scanners' real output to the PR, not a remembered list of ids.
`plan` only through the path the project allows (Makefile target, CI);
`apply`, `destroy`, `import` and `state` never.
