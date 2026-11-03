# Reviewing a pull request

A review answers one question: is it safer to merge this PR or to leave it
out? Four axes feed the answer: practices, blast radius, security, and risk
of applying against risk of not applying.

The review is read-only. Do not push to the branch, do not resolve threads and
**do not post anything** on GitHub until the owner reads the draft and
confirms, on the owner's own PR too (squad rule 5). In the squad the
`verifier` reviews.

## 1. Collect

```bash
gh pr view <n> --json number,title,body,author,baseRefName,headRefName,files,additions,deletions
gh pr diff <n> > "$TMPDIR/pr-<n>.diff"
python3 -I "$PR/scripts/inventory.py" --diff "$TMPDIR/pr-<n>.diff"
gh pr checks <n>
gh pr view <n> --comments          # plan commented by CI, earlier reviews
```

Read in full every changed file where the diff hides the context: a changed
IAM policy, a module input, a function whose callers matter.

Find out whose PR it is; GitHub refuses `--approve` and `--request-changes`
from the author:

```bash
me=$(gh api user -q .login)
author=$(gh pr view <n> --json author -q .author.login)
[ "$me" = "$author" ] && self_review=yes || self_review=no
```

## 2. Check the body against the format

`--files` takes the kind from the PR's own files, not from the local checkout:

```bash
gh pr view <n> --json body -q .body > "$TMPDIR/pr-<n>.md"
gh pr view <n> --json files -q '.files[].path' > "$TMPDIR/pr-<n>.files"
python3 -I "$PR/scripts/pr_check.py" "$TMPDIR/pr-<n>.md" --files "$TMPDIR/pr-<n>.files" \
  --title "$(gh pr view <n> --json title -q .title)"
```

Each problem is a finding. `TITLE_*` is **Minor**, with the title you would
use in the Fix column; it becomes **Blocking** when the title describes a
different change (promises an add that is a delete, names a resource the PR
does not touch). A body that says a scan passed while `gh pr checks` shows it
failed or did not run is Blocking. The other format problems (missing section,
broken table, `Did not run`) are Minor. When the missing part is exactly the
one that would show the risk (Cost, Risk analysis, Scans in an infrastructure
PR), the verdict stays at "Comment" until it arrives, not "Request changes".

## 3. The four axes

### Practices

Name the source of each practice you hold the PR to: the repository's
`CLAUDE.md`, an ADR, a skill (`parallel-git`, `ci-cost`), the vendor's guide.
A practice without a source is an opinion; say so or drop it.

| Area | Look for |
|---|---|
| Terraform | Versioned modules; pinned provider and module versions; required tags; encryption with a customer-managed key where the service supports it; allowed account pinned in the provider; `prevent_destroy` or deletion protection on stateful resources; no secret in code or `.tfvars`; no committed state |
| IAM | No `"*"` action or resource without a one-line reason; conditions on trust policies; no long-lived access keys |
| Code | Errors handled at the boundary; a timeout on every network call; no blocking call inside an async runtime; a test of the changed behaviour; validated input |
| Pipeline | Actions pinned by version or SHA; minimal `permissions:`; no `curl \| sh` |

### Blast radius

What the change can break, for whom, in numbers. Count from the plan and the
diff, not from the PR body.

- Accounts and environments touched (stg, prod, management, audit).
- Resources destroyed or replaced (`delete`, `delete,create`) and whether any
  holds state: a bucket with objects, a database, an encryption key, a log
  archive.
- Shared resources: network, subnets, DNS zones, roles others assume, keys
  other stacks use, organisation policies, module outputs other stacks read.
- Consumers of a changed API, event, schema or output.
- Rollout shape: all at once, or staged behind an environment or a flag.

### Security

- Identity: new or widened permissions, trust relationships, cross-account
  access.
- Exposure: `0.0.0.0/0`, a public endpoint, a public bucket, new ingress.
- Data: encryption at rest and in transit, logging or audit turned off,
  shortened retention.
- Secrets: anything that looks like a key, token or password in the diff,
  fixtures and examples included. Cite file and line, never the value.
- Supply chain: a new dependency, an unpinned version, a third-party action.
- Injection and authorisation in application code.

Read the scan output itself. A green check proves the tool ran on what it was
configured to scan; confirm that covers the changed files.

### Risk of applying and of not applying

| | |
|---|---|
| Risk of applying | What can go wrong after the merge, how likely, how soon someone notices |
| Risk of not applying | What stays broken, exposed or blocked if this never lands |
| Rollback | Is it a revert? Does the revert lose data or recreate a resource? |

A risky PR that closes a bigger open risk can still be the right merge; say
which side is bigger and why.

## 4. Infrastructure PRs and tests

Do not ask an infrastructure PR for mutation or adversarial tests, and do not
count their absence as a failure. Ask for what proves IaC: the plan summary,
`terraform validate`, `terraform test` where the stack promises something,
and the scans.

## 5. Verify, then write

Reviewers produce false positives, this one included. Before a finding goes
into the draft, open the code it points at and confirm it. What does not hold
up goes.

The draft follows the repository's language (`pr_check.py --lang auto` says
which):

```markdown
**Verdict: Request changes.** <One sentence: the main reason.>

| Severity | Where | Problem | Fix |
|---|---|---|---|
| Blocking | `stacks/export/s3.tf:14` | <problem> | <fix> |
| Minor | `README.md` | <problem> | <fix> |

## Practices
## Blast radius
## Security
## Risk of applying and of not applying
```

Severity is narrow on purpose: the review blocks a colleague's PR only when
the merge would break something.

**Blocking**: real breakage, a security exposure or a regression risk:

- an outage, an `apply` or pipeline that fails, a build that no longer runs;
- data loss, or state that a new run does not recover;
- a security exposure: public access, widened IAM, a secret in the diff,
  injection, an authorisation hole;
- a regression in behaviour another system or user depends on: a contract
  removed or changed, a stateful resource replaced, an unhandled error at the
  boundary;
- a changed money, data or credential path that the PR's tests leave unproven;
- a false claim in the body (a scan reported green that did not run).

**Minor**: everything else worth saying: a gap that fits in a follow-up PR,
naming, documentation, a test for behaviour the PR did not touch, a `TITLE_*`
finding, cleanup. Comment and approve.

**Nit**: not worth a comment unless the owner asks.

Verdict: "Approve" when nothing is Blocking, even with Minor comments.
"Request changes" only with a Blocking finding. "Comment" when the review
needs an answer before deciding. Never request changes for style,
documentation, naming or the title.

In the `verifier`: a Blocking finding fixable on the branch → FIX_FIRST; a
Blocking finding on the automatic REJECT list (committed secret, real network
or model in the suite, a test removed without an argument, a path forbidden
for the card's type) → REJECT; no Blocking finding → SHIP, with the Minor ones
as warnings.

## 6. Build the review (post only with the owner)

Write the verified findings as JSON, one object per finding: `path` and
`line` in the PR's version of the file (`"side": "LEFT"` for a removed line,
`start_line` for a range), `problem`, and the `fix` the author should make.
Add `suggestion` with the new lines when the fix is code: on a line of the new
file GitHub shows it as a one-click change; on a removed line it becomes a
plain block.

```json
[{"severity": "Blocking", "path": "stacks/export/s3.tf", "line": 14,
  "problem": "The bucket has no public access block.",
  "fix": "Add the public access block with all four options on.",
  "suggestion": null}]
```

`scripts/review_comments.py` turns the findings into the payload (it accepts
`Blocking`/`Minor` or `Bloqueante`/`Menor`; `--lang pt` for a Portuguese
repository). A finding on a diff line becomes an inline comment; GitHub
refuses comments outside the diff, so the rest go in the body, under "Outside
the diff".

```bash
head=$(gh pr view <n> --json headRefOid -q .headRefOid)
python3 -I "$PR/scripts/review_comments.py" --diff "$TMPDIR/pr-<n>.diff" \
  --findings "$TMPDIR/findings-<n>.json" --commit "$head" \
  --verdict "<one sentence: the main reason>" > "$TMPDIR/review-<n>.json"
```

On the owner's own PR (`self_review=yes`) add `--self-review`: the event
becomes `COMMENT`, because GitHub refuses approval or change requests from the
author, and the verdict goes in the body. Either way, show the owner the
verdict and the comments; only after they confirm:

```bash
[ "$(gh pr view <n> --json headRefOid -q .headRefOid)" = "$head" ] ||
  { echo "the PR moved during the review: fetch the diff again"; false; } &&
gh api repos/{owner}/{repo}/pulls/<n>/reviews --method POST --input "$TMPDIR/review-<n>.json"
```

A review on someone else's PR notifies the author and stays in the
repository's history: it is an outward action, always with the owner.
