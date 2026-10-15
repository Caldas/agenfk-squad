#!/usr/bin/env bash
#
# Diff-scoped mutation testing for a pull request: mutate only the LINES the branch changed.
#
# StrykerJS 10 has no `--since`; its `--incremental` depends on a stored result file surviving in a
# CI cache, and a cache miss silently turns a short job into a full run. So the diff is computed
# here, explicitly, and handed to Stryker as an exact `--mutate` list of line ranges (see
# changed-ranges.mjs). No cache, no hidden state, and the same command reproduces locally what CI did.
#
# Usage:  mutation-since.sh [base-ref]                         (default: origin/main)
#   TARGETS="name:config.mjs:path/prefix/ other:other.mjs:pkg/src/"   one Stryker config per prefix
#   STRYKER_BREAK=60                                            the PR run's floor (see below)
#
# Needs real history: `actions/checkout` with `fetch-depth: 0`, or the merge-base has nothing to
# resolve against. Run it AFTER the cheap gates (`needs:` + `if: needs.<job>.result == 'success'`),
# so a red or superseded commit burns no mutation minutes.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_REF="${1:-origin/main}"
: "${TARGETS:?set TARGETS=\"name:stryker-config.mjs:path/prefix/ ...\"}"

if ! git rev-parse --verify --quiet "$BASE_REF" >/dev/null; then
  echo "::error::mutation-since: base ref '$BASE_REF' not found (shallow checkout? set fetch-depth: 0)."
  exit 1
fi

# What THIS branch changed since it diverged, not what main did meanwhile. core.quotePath=false:
# otherwise git prints a non-ASCII path quoted and octal-escaped, the prefix filter below misses it,
# and the file is skipped while the job stays green.
if ! MERGE_BASE="$(git merge-base "$BASE_REF" HEAD)"; then
  echo "::error::mutation-since: no merge-base between '$BASE_REF' and HEAD (unrelated histories?)."
  exit 1
fi
CHANGED="$(git -c core.quotePath=false diff --name-only --diff-filter=d "$MERGE_BASE" HEAD -- '*.ts' '*.js' '*.mjs' || true)"

# The PR run asks "is the code THIS branch wrote tested?", not "has the whole scope rotted?" (that
# is the scheduled full run's ratchet). With line ranges the sample is small (~10 mutants for a
# 3-line change), so one or two survivors swing the score: watch the first PRs for false reds.
export STRYKER_BREAK="${STRYKER_BREAK:-60}"

# Stryker's CLI `--mutate` REPLACES the config's `mutate` array, so the config's own `!` exclusions
# are re-appended, read from the config itself so this script never carries a second copy of them.
exclusions_of() {
  node --input-type=module -e "
    const config = (await import('$(pwd)/$1')).default;
    console.log((config.mutate ?? []).filter((p) => p.startsWith('!')).join(','));
  "
}

run_target() {
  local name="$1" config="$2" prefix="$3"
  local files ranges excluded mutate
  # A prefix that names nothing in the tree is a typo, not "no changes": fail instead of skipping green.
  if ! git -c core.quotePath=false ls-files | grep -qE "^${prefix}"; then
    echo "::error::mutation-since: TARGETS prefix '${prefix}' (${name}) matches no tracked file."
    return 1
  fi
  files="$(printf '%s\n' "$CHANGED" | grep -E "^${prefix}" | grep -vE '\.(test|spec)\.(ts|js|mjs)$' || true)"
  if [ -z "$files" ]; then
    echo "mutation-since: no changed files under ${prefix} — skipping ${name}."
    return 0
  fi
  # shellcheck disable=SC2086 # one path per word; keep source paths free of spaces
  ranges="$(node "$HERE/changed-ranges.mjs" "$MERGE_BASE" $files)"
  if [ -z "$ranges" ]; then
    echo "mutation-since: no changed lines under ${prefix} — skipping ${name}."
    return 0
  fi
  excluded="$(exclusions_of "$config")"
  # Ranges first, then the `!` exclusions: Stryker applies the list in order, so an excluded file is
  # dropped whole whatever ranges it had.
  mutate="$(printf '%s\n' "$ranges" | paste -sd, -)"
  [ -n "$excluded" ] && mutate="${mutate},${excluded}"
  echo "mutation-since: ${name} — $(printf '%s\n' "$ranges" | wc -l) changed range(s), break=${STRYKER_BREAK}"
  printf '%s\n' "$ranges" | sed 's/^/  /'
  # --allowEmpty: a changed range with no mutant (a comment, a type) is a pass, not a failure.
  ./node_modules/.bin/stryker run "$config" --mutate "$mutate" --allowEmpty
}

for target in $TARGETS; do
  IFS=: read -r name config prefix <<<"$target"
  run_target "$name" "$config" "$prefix"
done
