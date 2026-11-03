# AWS prices: us-east-1 reference sheet

> **Dated.** Seed values reviewed on **2026-08-12** in the original skill pack;
> the data-transfer lines and traps 9 to 13 were added on **2026-08-26**
> without a check against the pricing API. Copied into the squad on
> 2026-10-14 without a new check. These are **draft** numbers, not a quote:
> check any line above $50/month against the pricing API (below) or with
> `finops` before putting it in the PR, and mark `~approx, unchecked` whatever
> you could not check. For OCI use the project's own OCI cost skill, if it has
> one, or `finops`; Alibaba and Cloudflare go to `finops` with the official
> pricing page.

Month = **730 hours**. On demand, `us-east-1`, USD, before tax.

## The three cost classes

Every resource in the diff falls into exactly one, and every resource appears
in the table: a $0.00 line with a reason is information; an omitted line is a
hole.

- **Fixed**: billed per hour, used or not. This is where the surprise comes
  from: it starts at the end of the apply.
- **Usage**: per GB, request, invocation. Needs a declared assumption.
- **Free**: the resource itself is not billed.

## Fixed monthly

| Resource | Unit price | $/month (730 h) | Notes |
|---|---|---|---|
| NAT Gateway | $0.045/h | **32.85** | plus $0.045/GB processed — the classic surprise |
| Application Load Balancer | $0.0225/h | **16.43** | plus $0.008/LCU-h |
| Network Load Balancer | $0.0225/h | **16.43** | plus $0.006/NLCU-h |
| Public IPv4 address (incl. EIP, attached or not) | $0.005/h | **3.65** | charged since Feb 2024 for every public IPv4 |
| Interface VPC Endpoint (per AZ) | $0.01/h | **7.30** per AZ | plus $0.01/GB — three AZs is $21.90/month |
| Transit Gateway attachment | $0.05/h | **36.50** | plus $0.02/GB |
| RDS `db.t4g.micro` Single-AZ | $0.016/h | **11.68** | Multi-AZ doubles it |
| RDS `db.t4g.small` Single-AZ | $0.032/h | **23.36** | |
| RDS `db.t4g.medium` Single-AZ | $0.065/h | **47.45** | |
| RDS gp3 storage, Single-AZ | $0.115/GB-mo | — | billed on allocated, not used |
| RDS gp3 storage, Multi-AZ | $0.23/GB-mo | — | Multi-AZ doubles storage as well as instance hours |
| Aurora Serverless v2 | $0.12/ACU-h | **87.60** per ACU | minimum capacity is billed continuously |
| ElastiCache `cache.t4g.micro` | $0.016/h | **11.68** | |
| OpenSearch `t3.small.search` | $0.036/h | **26.28** | plus $0.122/GB-mo gp3 |
| Fargate, 0.25 vCPU / 0.5 GB, always on | $0.04048/vCPU-h + $0.004445/GB-h | **9.01** | per task |
| Fargate, 1 vCPU / 2 GB, always on | as above | **36.04** | per task |
| App Runner, 1 vCPU / 2 GB, idle | $0.007/GB-h provisioned memory | **10.22** | CPU billed only while serving |
| App Runner, 1 vCPU / 2 GB, always active | + $0.064/vCPU-h | **56.94** | |
| SageMaker endpoint `ml.m5.large` | $0.115/h | **83.95** | |
| Route53 hosted zone | $0.50/mo | **0.50** | plus $0.40 per million queries |
| KMS customer-managed key | $1.00/mo | **1.00** | plus $0.03 per 10k requests |
| Secrets Manager secret | $0.40/mo | **0.40** | plus $0.05 per 10k API calls |

## Usage

| Resource | Unit price | Assumption needed |
|---|---|---|
| S3 Standard storage | $0.023/GB-mo | GB stored |
| S3 Standard-IA | $0.0125/GB-mo | GB stored, plus retrieval |
| S3 Glacier Instant Retrieval | $0.004/GB-mo | GB stored |
| S3 PUT/COPY/POST/LIST | $0.005 per 1,000 = $5.00/million | writes per month |
| S3 GET/SELECT | $0.0004 per 1,000 = $0.40/million | reads per month |
| Data transfer out to internet | $0.09/GB | egress GB. The 100 GB/mo free allowance is **account-level** and the existing estate consumes it — an incremental estimate never spends it again |
| Data transfer between AZs, same VPC | **$0.02/GB moved once** — $0.01 billed on egress and $0.01 on ingress | GB crossing the AZ boundary per month, counted one way |
| Data transfer over VPC peering, same region | free within an AZ; $0.02/GB moved once across AZs | GB across the peering per month |
| Data transfer out of us-east-1 to another region | $0.02/GB | GB leaving the region per month |
| Data transfer out of ap-southeast-2 to another region | **$0.098/GB** — ~5× us-east-1 | GB leaving Sydney per month; a round trip bills each leg at its own origin's rate |
| NAT Gateway data processing | $0.045/GB | GB through the NAT per month |
| NAT Gateway to the internet | **$0.135/GB** — $0.045 processing **plus** $0.09 transfer out; they compose, they are not alternatives | GB leaving AWS from a private subnet |
| Interface VPC Endpoint data processing | $0.01/GB | GB through the endpoint per month |
| NLB cross-zone data | $0.02/GB moved once; **off by default** | GB across zones per month (ALB: not billed) |
| DynamoDB on-demand writes | $1.25/million WRU | writes per month |
| DynamoDB on-demand reads | $0.25/million RRU | reads per month |
| DynamoDB storage | $0.25/GB-mo | GB stored |
| Lambda requests | $0.20/million, first 1M/mo free | invocations |
| Lambda duration | $0.0000166667/GB-second, first 400k GB-s free | memory × avg duration × invocations |
| SQS standard | $0.40/million requests, first 1M free | messages (×2 for send+receive) |
| SQS FIFO | $0.50/million requests | messages |
| SNS publishes | $0.50/million | messages |
| CloudWatch Logs ingestion | $0.50/GB | log GB per month |
| CloudWatch Logs storage | $0.03/GB-mo | retained GB |
| CloudWatch custom metric | $0.30/metric-mo | metric count |
| API Gateway HTTP API | $1.00/million | requests |
| API Gateway REST API | $3.50/million | requests |
| CloudFront data out | $0.085/GB first 10 TB | egress GB |
| CloudFront HTTPS requests | $0.0075 per 10,000 | requests |
| Step Functions | $0.025 per 1,000 state transitions | transitions |
| ECR storage | $0.10/GB-mo | image GB |
| EFS Standard | $0.30/GB-mo | GB stored |

## Free: list it anyway

| Resource | Why $0.00 |
|---|---|
| `aws_s3_bucket` itself | only stored objects and requests cost |
| Gateway VPC Endpoint (S3, DynamoDB) | no hourly charge, no data charge |
| Security group, NACL | free |
| Subnet, route table, internet gateway | free (the NAT Gateway is not) |
| IAM role, policy, instance profile | free |
| CloudWatch log group with no ingestion | free until logs arrive |
| ACM public certificate | free |
| DynamoDB table with no traffic and no data | free under on-demand |
| ECS cluster (no capacity providers) | free; the tasks cost |
| SSM Parameter Store standard parameter | free |

## Traps: always warn in the PR

1. **NAT Gateway**: $32.85/month + per GB, per AZ. Three AZs is ~$100/month
   before the first byte. Ask whether a gateway endpoint or a public subnet
   solves it.
2. **RDS Multi-AZ**: silently doubles the instance.
3. **Interface endpoints**: $7.30/month per AZ per endpoint. Ten across three
   AZs = $219/month.
4. **Aurora Serverless v2**: the minimum capacity is always billed; 0.5 ACU is
   ~$44/month idle.
5. **Public IPv4**: every one, including a Fargate task's with
   `assign_public_ip = true`.
6. **OpenSearch**: no useful free tier; the smallest useful cluster is
   ~$80/month.
7. **Log group with no retention**: ingestion is cheap, keeping forever is
   not. Always `retention_in_days`.
8. **Provisioned DynamoDB with little traffic**: on-demand usually comes out
   cheaper below ~20% utilisation.
9. **S3 or DynamoDB through the NAT**: $0.045/GB for traffic the gateway
   endpoint carries for free. Invisible in the plan.
10. **Internet egress from a private subnet**: $0.135/GB, not 0.09: NAT and
    egress add up.
11. **Anything cross-region**: not a warning, a stop (`network-topology.md`).
12. **NLB with cross-zone on**: 0.02/GB for traffic the ALB carries free.
13. **Multi-AZ storage**: doubles allocated storage: 100 GB costs 11.50
    single-AZ and 23.00 Multi-AZ.

## Not estimated by default

Declare as **Not estimated**, with the reason, never as $0.00:

- model invocation (per token, depends on the model and the product's usage);
- support plan;
- whatever depends on a third party (Cloudflare, an observability tool);
- a resource type outside the tables above.

**Data transfer is never on this list.** Every per-GB path declared in the
network placement gets a line. With no traffic model, give a **derived
range**: request rate × payload size, a measured number (CloudWatch, CUR) or a
number the request brought. A range with no derivation is a guess: it goes
under Not estimated with the path named.

| Resource | Spec / assumption | Class | $/month |
|---|---|---|---|
| Cross-AZ reads, app → RDS | 50–200 req/s × 4 KB avg row → 500–2,000 GB/mo, **derived from the API's own request rate, unconfirmed** | usage | 10.00–40.00 |

## Ephemeral resources

A short-lived resource (load test, one-off job, spike environment) still
carries the **monthly ceiling** (price × 730 h) in the `$/month` column and in
the Total, and the real window's cost in an extra `Expected this run` column.
Both, never one instead of the other: "$0.10" alone looks free and hides what
it costs when forgotten running. The "> $100/month" warning (SKILL.md, step 8)
is judged on `Expected this run`, not on the ceiling.

| Resource | Spec / assumption | Class | $/month | Expected this run |
|---|---|---|---|---|
| Fargate task, 1 vCPU / 2 GB | one 2 h batch run | fixed | 36.04 | 0.10 |

## Checking against the pricing API

The pricing API is free and its endpoint is in `us-east-1`. Read-only, with
the session the owner has already authenticated; the skill neither asks for
nor creates a credential.

```bash
aws pricing get-products \
  --region us-east-1 \
  --service-code AmazonRDS \
  --filters 'Type=TERM_MATCH,Field=instanceType,Value=db.t4g.micro' \
            'Type=TERM_MATCH,Field=deploymentOption,Value=Single-AZ' \
            'Type=TERM_MATCH,Field=databaseEngine,Value=PostgreSQL' \
            'Type=TERM_MATCH,Field=regionCode,Value=us-east-1' \
  --max-items 1 \
  --output json | jq -r '.PriceList[0]' | jq '.terms.OnDemand'
```

| Service | `--service-code` |
|---|---|
| EC2, NAT Gateway, EIP, data transfer | `AmazonEC2` |
| VPC endpoints | `AmazonVPC` |
| Load balancers | `AWSELB` |
| S3 | `AmazonS3` |
| RDS | `AmazonRDS` |
| DynamoDB | `AmazonDynamoDB` |
| Lambda | `AWSLambda` |
| Fargate / ECS | `AmazonECS` |
| App Runner | `AWSAppRunner` |
| SQS / SNS | `AWSQueueService` / `AmazonSNS` |
| CloudWatch | `AmazonCloudWatch` |
| Secrets Manager | `AWSSecretsManager` |
| KMS | `awskms` |
| Route53 | `AmazonRoute53` |
| OpenSearch | `AmazonES` |
| ElastiCache | `AmazonElastiCache` |
| EFS | `AmazonEFS` |
| ECR | `AmazonECR` |
| API Gateway | `AmazonApiGateway` |
| CloudFront | `AmazonCloudFront` |

Checked it? Update the line here and the date at the top, in the same PR to
the skill. Could not (no credential, rate limit)? Use the seed value and mark
the line `~approx, unchecked` in the PR.
