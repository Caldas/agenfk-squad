# Cost in the PR: what infra puts in the body

Applies to a PR that instantiates a resource in a stack. A module PR
instantiates nothing: the cost table and the network path go in the PR of the
stack that consumes it (`modules.md`).

The reviewer does not have the request's context. The body stands on its own:
someone who has never heard of the project approves it safely in five minutes.

## Who opens it and in what format

- The branch and the commit belong to `infra`, in the project's style. The PR
  is opened by `github`, after the `verifier`'s SHIP. The reviewer is the
  owner.
- The body follows the project's PR template or PR skill, which wins. The
  sections below go **inside** it: the cost table in the cost section, the
  network path right after it, the rest wherever the project's format asks.
- Language: what the owner asked for > the repo's language (CLAUDE.md, recent
  PR titles) > English. The labels below are translated along with it.
- Number of approvals and protections: read them from the repo or ask; do not
  assume.

## The infra sections

```markdown
> **Where it lives:** `<repo>/<path>`: triage, question <1|2|3>: <one sentence
> on why this destination and not the other two.>

### Estimated monthly cost: <region>

| Resource | Spec / assumption | Class | $/month |
|---|---|---|---|
| <resource> | <size, quantity or usage assumption> | fixed · usage · free | <n.nn> |
| **Total** | | | **<n.nn>** |

**Assumptions:** <each usage line's assumption and who confirmed it, or
"default, unconfirmed" when the request did not answer.>
**Not estimated:** <what the estimate does not cover, with the reason, or "nothing".>
**Prices:** <"reference sheet of <date>, unchecked" or "checked against the
pricing API on <date>" or "quoted by finops on <date>">

> **Cost warning:** <trap from `aws-prices.md` or a delta > $100/month.>

### Network path

- **VPC:** `<id>`: comes in through `vpc_id`, not created here.
- **AZs:** `<use1-az1, use1-az2>`: by id, as input; <why this many, or "no AZ
  control: App Runner/Lambda">
- **Region:** `<region>`: the same as every dependency.
- **Gateway endpoint:** <"exists in the VPC" · "missing: NAT cost below until it exists">

| Dependency | Path | Per GB | GB/month | Derived from |
|---|---|---|---|---|
| <who it talks to> | <same AZ · cross-AZ · gateway endpoint · interface endpoint · NAT within AWS · NAT to internet · public subnet> | <0.00> | <n or range> | <rate × payload · measured · request data> |

<One line for each path that is not the first viable one on its ladder, with the why.>

> **Path warning:** <cross-region, new VPC, S3/DynamoDB through NAT, single NAT
> in prod, NLB cross-zone, single-AZ prod database: each is the owner's
> decision, not an approval.>

### Deviations

<Compute outside the default, public bucket, `Resource = "*"`, AWS-managed key
instead of the customer's (name the key, e.g. `aws/s3`, and the scanner's
inline suppression), local state by the project's choice. One line of why
each. Or "none".>

### Impact of applying

<For someone who does not read HCL: how many resources, what holds state, what
has deletion protection, whether any existing resource is touched, whether
anything goes down.>

### How to read the plan

Expect <N to create, M to change, 0 to destroy>. **Any `delete` or `replace`
stops the approval**: comment instead of approving. <Where the plan shows up:
the project's CI, the Makefile target, or "plan not run: the project does not
allow a local plan".> The scanners' real output is attached below, not
summarised.

### Undo

<How to undo: revert and a new apply by the owner. For durable data:
`prevent_destroy` makes removal a deliberate two-step move, on purpose.>
```

## Rules

- **The cost table is mandatory**, even when everything is free: six lines of
  0.00 with a reason say more than a missing section.
- **Every resource in the diff appears in the table.** None rounded away.
- **The Total is always a full month** (as if it ran all month). An ephemeral
  resource adds the `Expected this run` column, never replaces it
  (`aws-prices.md`).
- **Every GB/month figure says where it came from.** A number with no source
  is a guess: it goes under Not estimated with the path named.
- **The network path is mandatory**; "no network dependency" is a valid answer
  and still gets the section. Every per-GB path becomes a line in the cost
  table.
- **The triage is mandatory**: destination and reason, one sentence.
- Plain HCL because there is no module → the line "Module candidate: `<name>`".
- New cloud resource: the `finops` quote (or the note that it was not
  consulted, and why) goes under Assumptions.
- No adoption-metric label or footer.
