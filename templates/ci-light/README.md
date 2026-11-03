# ci-light: a cheap GitHub CI for projects sealed by AgenFK

`ci-light.yml` is a **template**. It is not the CI of this repository; copy it
into a project that adopts the squad.

It runs only cheap checks: lint, terraform `fmt`/`validate`, semgrep and trivy.
It runs **no tests and no build**. The goal is under 5 minutes per run.

## Why the suite does not run here

In a squad project, tests, build and heavy review (REVIEW, ADVERSARIAL,
MUTATE, VERIFY) run inside AgenFK **before** the PR is opened. A card only
advances when its flow step passes with evidence, and leaving the
implementation step runs the project's suite. The code that reaches the PR
already carries that seal.

The watcher (`squad-watch`) blocks a merge to the trunk that lacks the seal.
Running the full suite again on GitHub would double the cost and the wait,
and it would add no new evidence. What GitHub still does well and cheaply,
on every PR and on every trunk push, is:

- catching a lint or format slip made after the seal;
- static security analysis (semgrep) and a scan for known vulnerabilities,
  leaked secrets and misconfiguration (trivy);
- checking that Terraform is formatted and internally valid, without touching
  any account.

If a project does not use the AgenFK seal, this template is **not enough** on
its own: add a test job or keep the project's existing test workflow.

## How to adopt it in a project

1. Copy the file:

   ```bash
   mkdir -p .github/workflows
   cp <path-to-agenfk-squad>/templates/ci-light/ci-light.yml .github/workflows/ci-light.yml
   ```

2. Review the `env:` block at the top and pin the versions the project uses:
   `TERRAFORM_VERSION`, `NODE_VERSION_FALLBACK`, `PNPM_VERSION_FALLBACK`,
   `TRIVY_VERSION`. If the trunk is not `main`, change `on.push.branches`.
3. Run the same checks locally once, before you open the PR that adds the
   workflow. A first semgrep or trivy run on an old codebase can report
   existing findings, and those findings fail the job:

   ```bash
   semgrep scan --config p/default --error --metrics=off
   trivy fs --scanners vuln,secret,misconfig --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 .
   terraform fmt -check -recursive
   ```

4. Open a PR with the workflow and check that each job either runs green or
   shows as skipped for the right reason.
5. In branch protection (or a ruleset) for the trunk, require the single check
   **`ci-light`**. It is an aggregator job: it fails if any other job failed
   or was cancelled, and it passes when a job was skipped because the
   repository has nothing for it. This keeps one stable required check
   whatever the project's language mix.

## Jobs

Every job checks out with `persist-credentials: false` and asks for
`contents: read` only. The workflow sets `permissions: {}` at the top, so a
job without its own `permissions` block gets no token scope at all. None of
the jobs writes to the repository, comments on the PR or uploads SARIF.

| Job | Runs when | What it does | Needs |
|---|---|---|---|
| `detect` | always | Looks at the tree and decides which jobs run. | `contents: read` |
| `lint (node)` | the root `package.json` has a `lint` script | Installs dependencies (`pnpm install --frozen-lockfile` or `npm ci`; without a lockfile, a plain install) and runs `pnpm run lint` or `npm run lint`. pnpm is chosen when there is a `pnpm-lock.yaml` or `packageManager` starts with `pnpm@`; otherwise npm. | `contents: read`. For pnpm, set `packageManager` in `package.json` (otherwise `PNPM_VERSION_FALLBACK` is used). Node comes from `.nvmrc` / `.node-version`, otherwise `NODE_VERSION_FALLBACK`. Private registries need an extra `NODE_AUTH_TOKEN` secret and `registry-url`, which the template does not set. |
| `lint (ruff)` | any tracked `*.py` file or a `pyproject.toml` | `ruff check` with the project's ruff config, or ruff's default rules when there is none. | `contents: read` |
| `terraform (fmt, validate)` | any tracked `*.tf` file | `terraform fmt -check -recursive -diff`, then in every directory with `.tf` files: `terraform init -backend=false` and `terraform validate`. | `contents: read`. **No cloud credential**: there is no backend, no state, no `plan` and no `apply`. Modules pulled from private Git hosts or a private registry will fail `init` unless you add credentials for them. |
| `semgrep` | always, except PRs opened by Dependabot | With `SEMGREP_APP_TOKEN`: `semgrep ci` (rules and triage from the Semgrep AppSec Platform, diff-aware on PRs). Without it: `semgrep scan --config p/default --error --metrics=off`, a full scan with the public ruleset. | `contents: read`. **`SEMGREP_APP_TOKEN` is optional** (repository or organisation secret). PRs from forks receive no secrets and fall back to the public ruleset. |
| `trivy (vuln, secret, misconfig)` | always | `trivy fs` on the tree with the `vuln`, `secret` and `misconfig` scanners. Fails on `HIGH` and `CRITICAL`. | `contents: read`. The action uses the default `GITHUB_TOKEN` to download the trivy binary and pulls its DB from a public registry; no extra secret. |
| `ci-light` | always | Aggregates the results (see step 5 above). | none (`permissions: {}`) |

Notes:

- trivy runs with `ignore-unfixed: true`: a HIGH or CRITICAL vulnerability
  that has no fixed version yet does not fail the job, because there is
  nothing to upgrade to. Set it to `false` if the project wants those too.
  To accept a specific finding, add it to a `.trivyignore` file at the root,
  with a comment saying why and until when.
- semgrep findings can be silenced in code with `# nosemgrep: <rule-id>`,
  with a reason in the same comment.
- The template does not install dependencies for trivy. It reads lockfiles
  (`package-lock.json`, `pnpm-lock.yaml`, `poetry.lock`, `uv.lock`,
  `go.sum`, and so on), so keep a lockfile committed if you want vulnerability
  results.
- Monorepos: lint detection looks only at the root `package.json`. Put a root
  `lint` script that fans out to the workspaces.
- yarn and bun are not detected. Edit the install and lint steps if the project
  uses them.

## How to switch a job off

Auto-detection already skips the jobs a repository has nothing for. To switch
a job off on purpose, add a condition that is always false, and leave a
comment saying why:

```yaml
  semgrep:
    # off: <reason>, <date>
    if: false
```

The `ci-light` gate still passes, because a skipped job counts as passed.
Do not delete the job from the gate's `needs` list unless you delete the job
itself; `needs` must only name jobs that exist.

Do not switch a job off with `continue-on-error: true`. It hides failures:
the job shows green while the check fails.

## Pinned versions

Every action is pinned to the full commit SHA of a release tag, and the tag
is in the trailing comment. The semgrep container is pinned by tag and digest.
Each SHA was checked against the release tag and against the action's
default branch history when the template was written:

| Pin | Release |
|---|---|
| `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1` | v7.0.1 |
| `actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1` | v7.1.0 |
| `pnpm/action-setup@ea17c68df8912ef543352723c149a84f56e3d413` | v6.1.0 |
| `astral-sh/ruff-action@278981a28ce3188b1e39527901f38254bf3aac89` | v4.1.0 |
| `hashicorp/setup-terraform@dfe3c3f87815947d99a8997f908cb6525fc44e9e` | v4.0.1 |
| `aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25` | v0.36.0 |
| `semgrep/semgrep:1.180.0@sha256:529ee8a277ec8adc5b534d7c74eea0a47e9de21d62852b6ba7ac6ba9566845c3` | 1.180.0 |

To bump a pin, resolve the new tag to its commit yourself and do not copy a
SHA from a blog post. A tag can be annotated, so dereference it until you reach
a commit:

```bash
gh api repos/<owner>/<repo>/git/ref/tags/<tag> --jq '.object'
# if .object.type is "tag", dereference it:
gh api repos/<owner>/<repo>/git/tags/<sha> --jq '.object'
```

Dependabot (`package-ecosystem: github-actions`) or Renovate can keep the SHAs
and the version comments up to date.

## Cost

GitHub-hosted `ubuntu-latest` minutes only, with no cloud resources. With
every job active, a run uses roughly 6 to 7 runner jobs of a few minutes each.
Public repositories do not pay for these minutes. Private repositories draw
on the account's included Actions minutes.
