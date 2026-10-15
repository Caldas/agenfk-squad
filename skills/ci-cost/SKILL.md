---
name: ci-cost
description: The squad's method for spending fewer CI minutes without loosening a gate — measure first (the billing API plus each run's jobs, the per-job rounded minute, minutes spent on cancelled jobs), then cut in order of gain - fewer and heavier jobs, the expensive job waiting for the cheap gates, PR mutation over the changed LINES (`scripts/changed-ranges.mjs` + `mutation-since.sh`, Stryker), a `paths` filter on the expensive job, duplicated tasks, the PR secret scan reading only the PR's commits. Use when the GitHub Actions quota runs out or gets close, when designing or reviewing a workflow, when a mutation or dry-run job dominates the bill, or when asked "how much does CI cost", "why is the PR slow", "where can we cut in CI".
---

# ci-cost — measure, then cut in order of gain

The failure this method prevents: cutting on a hunch. The job that "looks"
heavy is rarely the one that dominates the bill, and the easy cut (dropping a
test, skipping mutation) is exactly the forbidden one. **Never cut review,
tests or the mutation gate to save money**: cut what runs for nothing.

## 0. The project rules

Read `CLAUDE.md` / `AGENTS.md`, the workflow headers and the project's CI
decision records before changing anything. A job that is a *required check*
keeps its name; a task cache the project forbids stays forbidden; what the
project has already measured wins over any number here.

## 1. Measure (finops)

GitHub bills **every job separately and rounds each one up to the whole
minute**. A 61 s job costs 2 min; eight 70 s jobs cost 16.

```bash
# What the invoice says (org; personal account: /users/<user>/settings/billing/usage)
gh api "/orgs/<org>/settings/billing/usage?year=2026&month=10" \
  --jq '.usageItems[] | select(.product=="actions") | [.date,.sku,.quantity,.netAmount] | @tsv'

# What each job spent: sum ceil(duration/60) per job
gh api --paginate "/repos/<owner>/<repo>/actions/runs?created=>=2026-10-01&per_page=100" \
  --jq '.workflow_runs[].id' | while read -r id; do
  gh api "/repos/<owner>/<repo>/actions/runs/$id/jobs?per_page=100" --jq '.jobs[]
    | select(.started_at != null and .completed_at != null)
    | [.name, .conclusion, .head_branch,
       (((.completed_at|fromdate) - (.started_at|fromdate)) / 60 | ceil)] | @tsv'
done > jobs.tsv
```

On a real project the sum of the per-job ceil came within 2% of the invoice:
check it against the billing API before trusting it. Report, with the date
range:

- minutes per **job** (the ranking is the work list);
- minutes per **PR branch** and runs per branch (repeated pushes cost);
- minutes on **CANCELLED** jobs (a parallel job killed by a new push);
- the per-minute price with source and date (Linux 2-core: US$ 0.006/min,
  `docs.github.com/en/billing/reference/actions-runner-pricing`, read on
  2026-10-15) and the month's projection with and without the change.

**Measured example (a real project, 14 days):** 8,197 min against a quota of
3,000/month. PR mutation 18%, the PR deploy dry run 13%, 784 min on cancelled
jobs (330 of them mutation). Median mutation job 470 s, p90 2,265 s.

## 2. Cut, in order of gain

Write down the trade-off of each cut (what stops being proven where, and where
it is proven now). A cut without its trade-off written down does not go in.

1. **Fewer, heavier jobs.** Each job pays a setup (checkout, cache, install)
   and one rounding. Merge the light ones into a `preflight`; keep separate
   only the long pole of its group (splitting buys wall-clock, not minutes).
2. **The expensive job waits for the cheap gates.**
   `needs: [gates, test]` + `if: ${{ !cancelled() && needs.gates.result == 'success' && needs.test.result == 'success' }}`.
   A red commit, or one superseded by the next push, burns no minutes there.
   Only on a job that is **not** a required check (the name stays the same).
3. **PR mutation over the changed lines** (§3). The PR's question: "is the
   code THIS branch wrote tested?". The rest of the scope belongs to the
   scheduled full run.
4. **A `paths` filter on the expensive PR job** (deploy dry run, image build):
   only the inputs no suite proves — Dockerfile, entrypoint, manifests,
   lockfile, build tsconfig, the bootstrap file, the workflow itself. On push,
   the same positives followed by the negations (`!**/*.test.ts`, `!**/*.md`):
   GitHub reads `paths` in order, and a `!` after a positive drops the file.
   The trade-off to write down: a source regression that only the build
   catches shows up in main's build, which must run **before** anything is
   published.
5. **No duplicated task.** A `build` that is the same as `typecheck`
   (`tsc --noEmit`) runs twice under `turbo run typecheck build`. Look for
   identical scripts under different names.
6. **The PR secret scan reads the PR's commits**
   (`gitleaks git --log-opts="origin/main..HEAD"`); a push to main still scans
   the whole history. Keep the guards: the config is read from `origin/main`
   (never from the PR's tree), the ignore file is mounted empty, and a shallow
   clone is refused (`git rev-parse --is-shallow-repository`). Proof: a secret
   added and removed inside the same PR still fails (exit 1). Measured: 22 s
   for the full walk against 0.47 s for the range. A good side effect: one
   branch's fake secret no longer turns every PR red.

Outside this method: a task cache in CI (a replayed task is a gate that did
not run) and changing the runner. Those are the owner's decisions, with a
quote from `finops`.

## 3. Mutation by lines (Stryker)

`scripts/changed-ranges.mjs` turns `git diff -U0 <merge-base> HEAD` into
`path:start-end` entries for Stryker 10's `--mutate`; a new file goes in
whole. `scripts/mutation-since.sh` computes the merge-base, filters by prefix
and calls Stryker with the ranges plus the config's own `!` exclusions.

Measured: a 3-line change to a 675-line file went from **322 mutants / 252 s
to 10 mutants / 75 s** (66 s of the 75 is Stryker's fixed initial test run).

Rules the helper's tests lock in:

- a hunk that only **removes** lines yields `c..c+1`, so deleting a guard is
  still mutated;
- `---`/`+++` are file headers only before the file's first hunk;
- `git -c core.quotePath=false`, or a non-ASCII path is skipped while the job
  stays green;
- Stryker places a mutant only when its node lies **wholly** inside a range; a
  mutant that spans unchanged lines is not this gate's business.

A known effect: with ~10 mutants, `break=60` swings on one or two survivors.
Watch the first PRs before trusting a red, and do not loosen the threshold
without measuring.

### Wiring it into a CI

```yaml
# preflight (cheap): the helper has a test floor. A broken parser inside the
# mutation job would mutate nothing and pass.
- name: changed-ranges — helper tests
  run: |
    set -euo pipefail
    node --test --test-reporter=tap scripts/quality/changed-ranges.test.mjs | tee "$RUNNER_TEMP/ranges.tap"
    passed=$(awk '/^# pass /{print $3}' "$RUNNER_TEMP/ranges.tap")
    [ -n "${passed:-}" ] && [ "$passed" -ge 23 ] || { echo "::error::changed-ranges: '${passed:-no}' tests passed; floor is 23."; exit 1; }

mutation:
  needs: [preflight, gates, test]
  if: ${{ !cancelled() && github.event_name == 'pull_request' && needs.gates.result == 'success' && needs.test.result == 'success' }}
  steps:
    - uses: actions/checkout@<sha> # pinned
      with: { fetch-depth: 0 }     # no history, no merge-base
    # ...the project's setup and install...
    - run: scripts/quality/mutation-since.sh origin/main
      env:
        TARGETS: "api:stryker.api.mjs:apps/api/src/ web:stryker.web.mjs:apps/web/src/"
```

Copy `changed-ranges.mjs`, its test and `mutation-since.sh` into the project's
repository (they need nothing but Node and git) and run `node --test` locally
first.

## 4. Deliver

A before/after table per job (measured minutes, not estimates, once the run
exists), the written trade-off of each cut, and what is still **owed**: the
real number from the first run after the change. Changing the workflow belongs
to `infra`; measuring and projecting, to `finops`.
