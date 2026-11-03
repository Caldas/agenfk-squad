# Destination triage: where the resource lives

Answer this before writing a single line of HCL, and state the answer and the
reason out loud. If the project has a written rule for where each thing lives
(CLAUDE.md, an ADR, the infra `docs/`), it wins over this page.

Unless `project-map.md` or the project says otherwise, assume there is no
platform repository shared between projects. Do not invent one, nor create a
"platform" folder in the project to pretend there is.

## The three questions

In order. The first "yes" decides.

```
1. Does more than one project consume the resource, or does it outlive the project?
   → STOP and ask the owner where it lives. There is no default home.
2. Is it one project's only, but does it hold data that must survive the stack's destruction?
   → a root with its own state in the project (e.g. infra/data/), or, if the project
     does not want another root, the service stack with prevent_destroy + the native guard.
3. Everything else: born and dies with the stack.
   → the project's stack, where the repo already keeps its Terraform.
```

## Destination 1: shared

Examples: a VPC two projects use, a DNS zone for a common domain, a central
backup account, the account's audit trail. The question to the owner comes
with the concrete options (which repo, which state, who pays) and the cost.
Until the owner answers, no files.

Watch out for resources that already have an owner: the GitHub OIDC provider,
a CloudTrail trail, a DNS zone. Two states declaring the same resource fight on
every apply (the OIDC provider flaps on `thumbprint_list`). Search the repo
(`grep -rn` for the type) before declaring; if it exists elsewhere, consume it
through a data source.

A second CloudTrail trail is expensive: the first copy of each event is free,
every extra copy is billed per event. When in doubt, do not create one.

## Destination 2: durable data

Every durable data resource carries

```hcl
lifecycle {
  prevent_destroy = true
}
```

plus the native guard where there is one: `deletion_protection = true` (RDS,
DynamoDB), `skip_final_snapshot = false`, versioning on in S3,
`force_destroy = false`, a recovery window on secrets and KMS keys.

Name and ARN leave through an `output`. The service stack receives them through
tfvars or discovers them through a data source: by **name** where the provider
resolves by name (`aws_s3_bucket`, `aws_secretsmanager_secret`), by tag where
it supports it (`aws_vpc`, `aws_subnets`). **Never** `terraform_remote_state`:
it welds the stack to the other one's backend.

Produced a destination 2? Produce both sides: the durable root
(`templates/resource/durable-data.tf.example`) and the optional input in the
service stack (`templates/resource/durable-input.tf.example`). A PR with only
one side is incomplete.

### Durable by default

`aws_s3_bucket` · `aws_db_instance` · `aws_rds_cluster` · `aws_dynamodb_table` ·
`aws_elasticache_replication_group` (with snapshots) · `aws_efs_file_system` ·
`aws_opensearch_domain` · `aws_ecr_repository` · `aws_secretsmanager_secret` ·
`aws_kms_key` · `aws_backup_vault`. On OCI: Object Storage bucket, Autonomous
Database, vault. On Alibaba: OSS, RDS, KMS. On Cloudflare: R2, D1, KV holding
records.

### The exceptions: ask, do not assume

Some of these really are disposable: a build-artifact or log bucket with short
expiry, a DynamoDB table used only as a cache or a lock, the ECR repository of
a prototype. When the type is durable by default, ask the owner whether the
data must survive. Never silently promote a disposable bucket to durable, nor
silently leave a customer database in a stack someone can destroy.

## Destination 3: the project's stack

The common case: compute, its security groups, roles, alarms, DNS records,
queues. It goes where the repo already keeps its Terraform (see
`project-map.md`). Do not restructure a repo as a side effect of adding a
resource.

## Examples

| Resource | Destination | Why |
|---|---|---|
| User uploads bucket | 2 | uploads outlive the stack |
| CI artifact bucket, 7-day expiry | 3 | disposable by design |
| Subnet two projects use | 1, ask | more than one consumer |
| Security group of a service's ALB | 3 | dies with the service |
| The project's DNS record | 3, by variable | the record belongs to the project |
| The domain's DNS zone | 1, ask | one zone, several projects |
| The project's CI deploy role | 3 | scoped to that pipeline |
| GitHub OIDC provider | none, if it already exists | a second state flaps |
| DynamoDB sessions table | 2 | losing it logs everyone out |
| DynamoDB cache table | 3 | rebuildable |
| SQS retry queue between the project's services | 3 | not record data |
| The project's RDS | 2 | the obvious case |
| KMS key encrypting that database | 2 | destroying the key destroys the data |
| CloudWatch log group | 3 | retention, not record data |
| Secret holding a third-party API key | 2 | reissuing is manual |
| ECR repository of a production service | 2 | deleting it breaks rollback |
