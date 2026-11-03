# Network topology: affinity first, then the cheapest path that works

Two resources that talk have a *path*, and the path has a price, a latency and
a failure mode. None of it shows in the diff: a stack passes fmt, validate,
tflint and trivy while paying $0.135/GB to move bytes that never needed to
leave the VPC. This page makes the path a stated decision.

> **Prices:** AWS us-east-1, from the original pack dated 2026-08-26, *not*
> checked against the pricing API. They are draft numbers: check any line
> above $50/month against the pricing API or with `finops`. On OCI, use the
> project's own OCI cost skill, if it has one, or `finops`; by OCI's public
> price list (not checked here) cross-AD transfer is not billed and the first
> 10 TB/month of egress are free, so the ladder below changes price, not shape.

## Two decisions, not one ladder

Placement and egress are orthogonal. Decide them separately.

### A: placement, inside the VPC

| # | Placement | Price | When |
|---|---|---|---|
| 1 | Same AZ, private IP | free | the AZ can really be pinned (Fargate in one subnet, EFS, an ElastiCache node) |
| 2 | Same VPC, cross-AZ | $0.02/GB (0.01 on egress + 0.01 on ingress, per GB moved once) | the default for App Runner and Lambda, and wherever redundancy asks for it |

500 GB read + 500 GB written across AZs = 1,000 GB = $20.00, not 10. App
Runner and Lambda give no AZ control: they start on line 2 by construction,
and the transfer is a declared cost, not a defect. Do not force a single
subnet to save money: it trades $0.02/GB for compute in one AZ only.

### B: egress, for traffic that leaves the VPC

| # | Mechanism | Price | When |
|---|---|---|---|
| 1 | Gateway Endpoint (S3, DynamoDB) | free | reaching S3 or DynamoDB. Always, if it exists |
| 2 | Interface Endpoint / PrivateLink | $7.30/AZ-month + 0.01/GB | an AWS API with no gateway endpoint, called in volume |
| 3 | NAT, staying in AWS | $32.85/NAT-month + 0.045/GB | an AWS API not worth an endpoint |
| 4 | NAT, to the internet | $32.85/NAT-month + **0.135/GB** | internet egress from a private subnet |
| 5 | Public subnet via internet gateway | $0.09/GB | the resource already terminates public traffic |

**Line 4 is the one everybody gets wrong:** NAT processing (0.045) and AWS
egress (0.09) add up. A private Lambda writing 500 GB/month to S3 costs $0
through the gateway endpoint and $22.50 through the NAT: same code, same
bucket, one route-table entry nobody reads in the plan.

The 100 GB/month egress allowance is per account and already consumed: quote
the incremental egress in full.

### Cross-region: forbidden, not a rung

Never generate cross-region replication, a resource in a second region or a
consumer that reads from another region. Always the stack's region
(`var.aws_region`). Say it is the owner's decision and stop. For reference:
leaving us-east-1 costs $0.02/GB, leaving ap-southeast-2 costs 0.098/GB, and
the latency between the two is ~100 ms per leg. Legitimate cases (compliance,
regional latency, DR with a declared RPO) are the owner's written decision,
not a resource PR.

## Placement invariants

Generated, not suggested. A design that breaks one carries the reason in the
PR or is not generated.

### The VPC is an input, never created in a resource PR, never a literal

Creating a VPC is a decision of its own, with a chosen CIDR and its own PR.
Overlapping CIDRs cannot peer nor go through a Transit Gateway; the mistake is
practically permanent. One accidental VPC per project is how accounts end up
with five VPCs on the same `10.0.0.0/16`.

Network inputs take the same optional shape as the durable input:

```hcl
variable "vpc_id" {
  description = "Existing VPC. Empty: the environment uses no VPC, or the owner decides to create one."
  type        = string
  default     = ""
}

variable "private_subnet_ids" {
  description = "Existing private subnets."
  type        = list(string)
  default     = []
}

variable "availability_zone_ids" {
  description = "AZ ids (use1-az1, ...). Empty lets the provider choose."
  type        = list(string)
  default     = []
}
```

The real values go in `<env>.tfvars`. If the root discovers them through a data
source, the data source lives in the root, with a filter that identifies a
single VPC; with no tag that discriminates, pin the ids in the tfvars and say
so in the PR. Do not invent a filter and hope.

### The rest

- **Private subnet by default.** Public only for whatever terminates public
  traffic, and the PR says which.
- **A gateway endpoint has to exist; it does not have to be in this PR.** It
  belongs to the whole VPC and touches route tables the service stack does
  not own. If it is missing, it is a shared resource (triage, destination 1):
  ask the owner, and put in the PR the NAT cost paid until it exists.
- **AZ by id, never by name, never a literal in the code.** `us-east-1a` is
  not the same physical zone in two accounts; `use1-az1` is. The ids come in
  by variable or through `data.aws_availability_zones` in the root.
- **The number of subnets follows the redundancy the resource needs.** Three
  AZs is not a default: it triples per-AZ endpoints and NATs.
- **One NAT per AZ in prod; a single one is fine in test.** A single NAT makes
  the loss of one AZ take down all egress, and whoever reaches it from another
  AZ pays 0.02 + 0.045. A NAT is also shared networking: the resource PR says
  which NAT it goes through and what it costs, it does not create one.
- **EFS is AZ-local:** mounting it from another AZ pays transfer on every
  read.
- **ALB where both fit.** ALB cross-zone traffic is not billed; NLB's is
  0.01/GB each way. NLB is the right choice for TLS passthrough, UDP, a fixed
  IP; then leave cross-zone off (the default).
- **CloudFront for static content is a recommendation, not an invariant.** The
  argument is caching and origin load, not the per-GB price, which can flip
  depending on the edge's region. Justify it by the cache and quote it per
  region.

## App Runner and the VPC boundary

- Default egress is public. Reaching RDS or ElastiCache needs a **VPC
  connector**.
- Egress is all or nothing: `DEFAULT` or `VPC`. A service that needs a private
  database **and** an external API needs a NAT, the fixed cost the default was
  meant to avoid.
- With a connector and a gateway endpoint, S3 goes through the private, free
  path.

The PR says: connector or not, which subnets, and the path to each
dependency.

## Reliability is not traded for transfer

- **Prod, record data → Multi-AZ.** Standby replication is not billed; the
  cost is double instance and double storage (gp3 from 0.115 to
  0.23/GB-month).
- **Test → one AZ.**
- **A transfer bill is solved by changing who calls** (co-locate, cache,
  batch), not by deleting the AZ.
- Where reliability and cost really conflict, the PR states the trade-off and
  the owner decides.

## In the PR

The **Network path** section (`cost-in-pr.md`): a table of which path each
dependency takes, the assumed GB/month **and where the number came from**, and
the resulting transfer cost.
