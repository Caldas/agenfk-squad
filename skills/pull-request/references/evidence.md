# Where each section's facts come from

Each table in the body comes from a command's output, a `plan` or a CI check.
When the source is missing, the row says so (`Did not run: <reason>`,
`Outside the estimate: <reason>`). A number nobody measured does not go in the
body.

`$PR` is the skill's directory: `~/.claude/skills/pull-request`.

## Card, verdict and tests (squad flow)

```bash
agenfk get <id> --json                 # title, description, acceptance criteria, comments
agenfk get <id> --json | jq '.comments[] | select(.content | startswith("VERIFIER"))'
```

| Fact | Source | Goes to |
|---|---|---|
| The problem and what stays out | card description | Opening paragraph |
| Verdict, reproduced suite, mutation | `VERIFIER: SHIP ...` comment | Tests |
| Suites and counts | `agenfk log-test` recorded by the `tester` | Tests |
| Monthly cost and assumptions | `finops` quote commented on the card | Cost |
| `plan`, `validate`, IaC scans | `infra` report | Resources, Before and after, Scans |

Without the `verifier`'s SHIP the PR does not open; the body does not replace
the verdict.

## Files and declarations

```bash
git fetch origin
git diff --stat origin/main...HEAD
python3 -I "$PR/scripts/inventory.py" --repo . --base main                 # markdown tables (en)
python3 -I "$PR/scripts/inventory.py" --repo . --base main --lang pt
python3 -I "$PR/scripts/inventory.py" --repo . --base main --format json
```

`inventory.py` lists Terraform `resource`, `data` and `module` blocks and
function definitions the branch adds, removes or redeclares. It reads
declaration lines only: it is the draft of "Functions created and deleted" and
the cross-check of the resource tables. For resources, the source stays the
`plan`.

## Resources: created, deleted, before and after

In an infrastructure PR the source is the `plan`, run by `infra` with a
read-only profile; never `apply` from a PR session. Use the repository's entry
point when there is one (`make plan STACK=<stack> ENV=<env>`). Otherwise:

```bash
terraform plan -out=tfplan
terraform show -json tfplan | jq -r '
  .resource_changes[]
  | select(.change.actions != ["no-op"] and .change.actions != ["read"])
  | [(.change.actions | join(",")), .address] | @tsv'
```

| Action in the plan | Goes to |
|---|---|
| `create` | Resources created |
| `delete` | Resources deleted |
| `update` | Before and after, one row per attribute that matters to the reader |
| `delete,create` or `create,delete` (replace) | Created and deleted, plus a Risk analysis row: a replace recreates the resource |

When CI comments the plan on the PR, read it with `gh pr view <n> --comments`
and quote the summary line (`N to add, M to change, D to destroy`).

In an application PR, a "resource" is anything another system depends on: an
endpoint, queue, table, topic, scheduled job, feature flag, public type. Before
and after compares behaviour or contract.

## State and flow diagrams

Mermaid in a fenced block; GitHub renders it in the PR.

- `### State`: a `stateDiagram-v2` of the life cycle the PR creates or changes
  (an object, a job, a resource, a request).
- `### Flow`: a `flowchart` or `sequenceDiagram` of how the request or the data
  moves after the merge.

Draw only components that appear in the diff, the plan or the IaC, with fewer
than 15 nodes. With no life cycle or no flow (a typo, a tag change), the
subsection carries `None.` and the reason.

## Cost

The `finops` quote is the source: each resource in the diff has a row (fixed,
usage-based, or free with the reason), the estimate is what this PR adds, the
assumptions are visible, what cannot be priced goes under "Outside the
estimate", and an increase above US$ 100/month or a known trap (NAT Gateway,
Multi-AZ database, interface endpoint, public IPv4) gets a warning row. An
infrastructure PR states a dollar amount, even US$ 0.00. An application PR
with nothing billed writes `None.` and the reason.

## Scans

| Tool | Infrastructure PR | Application PR |
|---|---|---|
| Lint | The repository's entry point (`make check`), otherwise `terraform fmt -check`, `terraform validate`, `tflint` | The repository's own (`npm run lint`, `ruff check .`, `dotnet format --verify-no-changes`) |
| Semgrep | The CI check, or `semgrep scan --config p/default --error .` when installed | Same |
| Trivy | `trivy config --exit-code 1 .` | `trivy fs --scanners vuln --exit-code 1 .`; `trivy image <ref>` for a container |
| Secrets (gitleaks) | `gitleaks detect --no-banner --redact` (or `gitleaks git` in newer versions) | Same |

Read CI with `gh pr checks <n>`. For a tool that runs neither in the
repository nor on the machine, `Did not run: <reason>` is a valid answer.
Write the result as the tool gave it: passed or failed, the count and the run
link when there is one. Never paste the value of a secret that was found; cite
the file and line.

## Tests

Suite name, command and counts. Never "tests passing".

An infrastructure PR **carries no adversarial or mutation tests**: do not run
them and do not list them. The evidence is `terraform validate`,
`terraform test` (when the stack promises something: a cost ceiling,
`prevent_destroy`, variable validation), the plan summary and the scans.

An application PR may cite the mutation test the `verifier` ran: what was
broken and what failed.
