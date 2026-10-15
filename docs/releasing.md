# Releasing

This page is for the maintainer. Contributors only need the first section.

## Two branches

| Branch | What it holds | How a change gets in |
|---|---|---|
| `beta` | The default branch. Everything that has been reviewed and has passed CI | A pull request, reviewed, with green checks |
| `main` | The stable line. Only what was promoted from `beta`, plus hotfixes | A release pull request from `beta`, or a hotfix pull request |

Every pull request, the maintainer's included, targets `beta`. `main` moves
only when a release is cut.

The installer follows the same split. By default it installs the newest `v*`
tag on `main`; until the first tag exists, it installs the tip of `main`.
With `--beta` it installs the tip of `beta`. So a change reaches most users
when its release is tagged, not when its pull request is merged.

## Versions

Tags are annotated, on `main`, in the form `vMAJOR.MINOR.PATCH`. While the
project is at `0.x`:

- a release from `beta` raises the minor version: `v0.1.0`, `v0.2.0`;
- a hotfix raises the patch version: `v0.1.1`.

The first release is `v0.1.0`. A tag is never moved or deleted once pushed:
installs are pinned to it. A bad release is fixed by the next one.

## When to release

Promote `beta` when all of these hold:

- `beta` has something a user of the stable line should have;
- the checks are green on the tip of `beta`;
- `beta` has run in the maintainer's own daily sessions since its last
  behavioural change, and no open issue reports a regression in it.

A breaking change, as defined in [CONTRIBUTING.md](../CONTRIBUTING.md) (a
changed threshold, keyword or state path), can ship, but the release notes
must say so in their first line.

## Promote beta to main

The examples cut `v0.1.0`. Replace the version throughout.

### 1. See what will ship

```bash
git fetch origin --tags
git log --oneline origin/main..origin/beta
```

An empty list means there is nothing to release.

### 2. Rehearse the merge locally

Cheap, and it catches a conflict before the pull request does. Nothing here
is pushed.

```bash
git switch -c release-rehearsal origin/main
git merge --no-ff --no-edit origin/beta
python3 tests/test_watch.py
git merge-base --is-ancestor origin/beta HEAD && echo "beta SHAs preserved"
git switch -
git branch -D release-rehearsal
```

### 3. Open and merge the release pull request

```bash
gh pr create --repo eduardopin/agenfk-squad --base main --head beta \
  --title "Release v0.1.0" \
  --body "Promotes beta to main. Tag v0.1.0 follows the merge."
gh pr merge <number> --repo eduardopin/agenfk-squad --merge \
  --subject "Release v0.1.0"
```

Merge with a **merge commit**, never squash or rebase. A merge commit keeps
the commits of `beta` on `main` with the same SHAs. A squash would put one
new commit on `main` with the content of many, `beta` would never appear to
have been merged, and the next release would carry the same changes again.
The `main` ruleset below allows only merge commits, so the button cannot be
pressed by mistake.

`beta` does not need the merge commit back. After each release GitHub shows
`beta` as one commit behind `main`: that commit is the merge, and its content
is already in `beta`.

### 4. Tag the merge commit

Tag the merge commit of the release pull request itself, not the tip of
`main`: if anything else lands on `main` in between, the tip is the wrong
commit.

```bash
git fetch origin
sha=$(gh pr view <n> --json mergeCommit --jq .mergeCommit.oid)
git log -1 --oneline "$sha"
git tag -a v0.1.0 -m "v0.1.0" "$sha"
git push origin v0.1.0
```

`git log` must show the merge of the release pull request before you tag.
Pushing the tag is the release: from that moment the installer serves it.

### 5. Publish the release notes

```bash
gh release create v0.1.0 --repo eduardopin/agenfk-squad --verify-tag \
  --title "v0.1.0" --generate-notes
```

`--verify-tag` refuses to run if the tag was not pushed, so `gh` cannot
create a lightweight tag of its own. `--generate-notes` lists the pull
requests merged since the previous release. Put any breaking change above
that list, with `gh release edit v0.1.0 --notes-file <file>` or on the web.

## Hotfix

For a defect in the stable line that cannot wait for the next release.
Contributors still open their fix against `beta`; the maintainer decides
whether it also ships as a hotfix.

```bash
git fetch origin
git switch -c hotfix/short-name origin/main
# fix it, with a test that fails without the fix
python3 tests/test_watch.py
git push -u origin hotfix/short-name
gh pr create --repo eduardopin/agenfk-squad --base main \
  --title "Fix: what was broken"
gh pr merge <number> --repo eduardopin/agenfk-squad --merge
```

Then tag the patch version and publish notes, as in steps 4 and 5 above
(`v0.1.1`).

Last, bring the fix back to `beta`, also with a merge commit, so that the fix
has the same SHA on both branches:

```bash
gh pr create --repo eduardopin/agenfk-squad --base beta --head main \
  --title "Merge main into beta after v0.1.1"
gh pr merge <number> --repo eduardopin/agenfk-squad --merge
```

If that pull request conflicts, resolve it on a branch cut from `beta`
(`git switch -c sync/v0.1.1 origin/beta && git merge origin/main`) and open
the pull request from that branch.

## Branch protection

**A step for the repository owner.** These commands change the repository's
settings. Nothing in this repository runs them; the owner runs each once and
checks the result with `gh api repos/eduardopin/agenfk-squad/rulesets`.

The required checks are the jobs of [`tests.yml`](../.github/workflows/tests.yml).
If a job is renamed or added, update both rulesets, or pull requests will wait
for a check that never reports.

GitHub cannot restrict which branch a pull request into `main` comes from.
"Only release and hotfix pull requests into `main`" stays a rule of review;
the ruleset makes sure every change to `main` is a reviewed pull request,
merged with a merge commit, with green checks.

`main`: pull request only, merge commit only, checks green, no force push,
no deletion. No bypass, the owner included.

```bash
gh api --method POST repos/eduardopin/agenfk-squad/rulesets --input - <<'EOF'
{
  "name": "main: releases and hotfixes only",
  "target": "branch",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {"type": "pull_request", "parameters": {
      "required_approving_review_count": 0,
      "dismiss_stale_reviews_on_push": false,
      "require_code_owner_review": false,
      "require_last_push_approval": false,
      "required_review_thread_resolution": false,
      "allowed_merge_methods": ["merge"]
    }},
    {"type": "required_status_checks", "parameters": {
      "strict_required_status_checks_policy": false,
      "required_status_checks": [
        {"context": "watcher (3.10)"},
        {"context": "watcher (3.12)"},
        {"context": "watcher (3.14)"}
      ]
    }}
  ]
}
EOF
```

`beta`: pull request only, checks green, no force push, no deletion. Squash
is allowed for contributions; the `main` into `beta` pull request after a
hotfix must use the merge commit.

```bash
gh api --method POST repos/eduardopin/agenfk-squad/rulesets --input - <<'EOF'
{
  "name": "beta: reviewed and green",
  "target": "branch",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["refs/heads/beta"], "exclude": []}},
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {"type": "pull_request", "parameters": {
      "required_approving_review_count": 0,
      "dismiss_stale_reviews_on_push": false,
      "require_code_owner_review": false,
      "require_last_push_approval": false,
      "required_review_thread_resolution": false,
      "allowed_merge_methods": ["merge", "squash"]
    }},
    {"type": "required_status_checks", "parameters": {
      "strict_required_status_checks_policy": false,
      "required_status_checks": [
        {"context": "watcher (3.10)"},
        {"context": "watcher (3.12)"},
        {"context": "watcher (3.14)"}
      ]
    }}
  ]
}
EOF
```

Release tags: a pushed `v*` tag cannot be moved or deleted, since installs are
pinned to it.

```bash
gh api --method POST repos/eduardopin/agenfk-squad/rulesets --input - <<'EOF'
{
  "name": "release tags are immutable",
  "target": "tag",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["refs/tags/v*"], "exclude": []}},
  "rules": [
    {"type": "deletion"},
    {"type": "update"}
  ]
}
EOF
```

`required_approving_review_count` is 0 because the project has one
maintainer, and GitHub does not let an author approve their own pull request.
Raise it when there is a second maintainer.
