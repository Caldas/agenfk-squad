---
name: parallel-git
description: The squad's method for branches, worktrees, PR stacks and parallelism across sessions and AgenFK cards in any project — one card = one branch = one worktree = one session; parallel fronts only with disjoint files; a writer claim per worktree; a map of who is where (`claude agents --json`, `git worktree list`, `gh pr list`); a merge train with squash and `rebase --onto`; cleanup of dead worktrees and branches. Use when planning parallel work, before opening a worktree or branch, when stacking PRs, when two sessions collide on the same file, when a PR is orphaned, or when wrapping up the day.
---

# parallel-git — one card, one branch, one worktree, one session

The failure this method prevents: two sessions in the same checkout, where
one's `git status`, `git add -A`, build and tests see the other's half-done
work — and each can revert, stage or delete the other's files without
noticing. The second failure: the PR stack broken by a squash.

## 0. The project rules

Read `CLAUDE.md` / `AGENTS.md` and `infra/` before touching git: the trunk
(`main`, `dev`, `develop`), the branch prefix (`acme/`, `feat/`, `task/<id>`),
the merge type allowed, `delete_branch_on_merge`, hooks that refuse a merge
(`guardrail.sh`, `merge-to-main-guard.sh`), and the project's own worktree
scripts (`scripts/worktree/acme-worktree.sh`, `.claude/worktrees/`). **A
project script replaces the generic commands in here.**

## 1. Map: who is where (read-only, always first)

```bash
git fetch -q --prune
git worktree list --porcelain                       # worktrees and the branch of each
claude agents --json                                # live sessions: cwd, name, status
agenfk list --project <id> --active --json          # cards in progress and branchName
gh pr list --state open --json number,title,headRefName,headRefOid,baseRefName,isDraft
for w in $(git worktree list --porcelain | awk '/^worktree /{print $2}'); do
  echo "== $w"; git -C "$w" status --porcelain | head -5; done   # dirt per worktree
```

Cross the three: **session → worktree (cwd) → branch → card → PR**. Every row
missing one of the links is a finding: a worktree with no card (orphan), an
active card with no branch, a branch with no PR for days, a PR whose base was
deleted, two sessions in the same cwd.

## 2. Independent front = disjoint files

Before dispatching in parallel, write the table:

| Front | Card | Base (SHA) | Branch | Worktree | Files it may touch | Session/agent | Evidence of done |

- Two fronts that need the **same file** become one front, or run in series
  (the second is born from the first one's branch). `CHANGELOG.md`,
  `session-notes.md`, `HANDOFF.md`, lockfiles and migrations count: **one**
  front writes to them; the others hand back the text.
- Real dependency: B touches the same files as A, or consumes the contract A
  changes. The rest is convention and can move together.
- **Ceiling: ~4 simultaneous fronts.** Above that, queue — the limit is the
  review ceiling, not the CPU.
- Note the SHA of each base: it is what "did it do anything" is measured
  against.

## 3. Opening the front

```bash
agenfk branch create <item-id>                      # feature/<slug>, fix/<slug> for a BUG; records it on the card
# or link an existing one:
agenfk branch link <item-id> <branch>
git worktree add <worktrees-root>/<slug> -b <branch> origin/<trunk>   # or without -b if it already exists
```

Worktrees root: the project's (`<repo>/.claude/worktrees/`,
`../acme-worktrees/`). Never inside another worktree.

In the new worktree, register the writer — a file in the git dir **of the
worktree**, which never shows up in `git status`:

```bash
printf 'card=%s\nsession=%s\nat=%s\n' <item-id> "$(hostname):$$" "$(date -Is)" \
  > "$(git rev-parse --absolute-git-dir)/squad-claim"
```

Before writing in any worktree, read the claim; if it belongs to another
session and is less than 24h old, **do not write** — report the collision.

## 4. During

- Small commit, message in the project's convention, push the branch with
  `agenfk branch push <item-id>`.
- Never commit on the trunk; never `--force` on a branch another session may
  have; never `--no-verify`.
- Rebase the branch onto the trunk only by the owner of the front, and only
  while the branch has no open PR with a review in progress.
- Dependabot and automatic bumps: treat them as a front of their own, never as
  a ride-along.

## 5. PR stack and the merge train

**The merge turn belongs to the watcher.** With several sessions in the same
repository, merging is one at a time: `squad-turn request <PR>` first,
`squad-turn status` to see the queue, the branch's conflict with the trunk and
the files contested with whoever is ahead. Sync with the trunk only on your
turn, once; outside it main will still move. The train below is the order you
propose; the queue is what executes it.

Each PR is born with `--base` on the previous branch when it depends on it;
otherwise, on the trunk. Survey the stack and the conflicts **without touching
the tree**:

```bash
gh pr list --state open --json number,title,headRefName,headRefOid,baseRefName
gh pr checks <n>
git merge-tree --write-tree origin/<base> origin/<top>     # conflict without checkout
gh run view <run-id>                                       # ANNOTATIONS: billing × real defect
```

CI that fails in seconds without running a step is account/permission, not a
defect — read the annotation before concluding.

**Squash breaks the stack:** the squash of `k` creates a new commit on the
trunk; branch `k+1` still carries the original commits of `k` and starts
conflicting with itself. Before the first merge, save the original SHAs of
**all** the tips (`delete_branch_on_merge` deletes the base along with it).
After each squash:

```bash
git rebase --onto origin/<trunk> <original-SHA-of-k-tip> <branch-k+1>
gh pr edit <n(k+1)> --base <trunk>
```

Deliver the train as a **proposal**: the order, what needs a rebase after each
squash, what each merge unblocks. Every line with `merge` belongs to the owner.

## 6. Closing the front and cleaning up

```bash
git -C <worktree> status --porcelain          # empty, otherwise do not remove
rm -f "$(git -C <worktree> rev-parse --absolute-git-dir)/squad-claim"
git worktree remove <worktree>                # never --force on a dirty worktree
git worktree prune
git branch --merged origin/<trunk> | grep -vE '^\*|<trunk>'   # candidates; delete only with approval
```

Remote branch deleted but the local one still exists: `commit-commands:clean_gone`.

## 7. Collision signals and what to do

| Signal | Meaning | Action |
|---|---|---|
| two sessions with the same `cwd` | they will step on each other | pause the newer one (`/agenfk-pause`), move it to a worktree of its own |
| dirty worktree with no live session | abandoned work | do not delete; `git stash`/WIP commit on a `wip/<card>` branch and record it on the card |
| branch with no commit for > 7 days with an active card | dead or paused front | ask the owner; do not archive on your own |
| PR with a deleted base | stack broken by squash | §5 |
| `git status` shows a file the front was not allowed to touch | scope leaked | send it back to the implementer before the PR |
| conflict in `merge-tree` between two open fronts | the files were not disjoint | serialise; the second rebases onto the first |

## 8. Standard delivery

```
Map            [session → worktree → branch → card → PR, one line each; the missing links]
Fronts         [the table from §2]
Stack          [order, CI, conflict (merge-tree), blocker of each PR]
Proposed train [merge order + rebase needed after each squash — a proposal]
Collisions     [those from §7 and the suggested action]
Owner only     [merge, force, deleting a dirty branch/worktree, CI billing]
```
