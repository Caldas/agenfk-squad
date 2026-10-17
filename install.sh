#!/usr/bin/env bash
# Links the squad into the user level of Claude Code. Idempotent.
# Never overwrites a real file: it only creates or updates symlinks.
set -euo pipefail

SQUAD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"

link() {
  local src="$1" dst="$2" root real
  # Only what lives in this repository gets linked. A source that is itself a
  # symlink resolving elsewhere (a skill directory pointing at a download, say)
  # would put code nobody reviewed into every session.
  root="$(cd "$SQUAD" && pwd -P)"
  if command -v realpath >/dev/null 2>&1; then
    real="$(realpath "$src" 2>/dev/null)" || real=""
  else
    real="$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$src" 2>/dev/null)" || real=""
  fi
  case "$real" in
    "$root"/*) ;;
    *)
      echo "REFUSED $src resolves to ${real:-(unresolvable)}, outside the squad repository ($root)." >&2
      echo "        A third-party skill goes in as a copy under skills/vendor/<name>/, with a line in" >&2
      echo "        skills/vendor/LOCK (origin, commit, sha256 from python3 tests/test_vendor.py --hash" >&2
      echo "        skills/vendor/<name>). See \"Proposing a skill\" in CONTRIBUTING.md. The rest is still linked." >&2
      return 1
      ;;
  esac
  if [ -e "$dst" ] && [ ! -L "$dst" ]; then
    echo "SKIPPED $dst exists and is not a symlink — resolve it by hand" >&2
    return 1
  fi
  ln -sfn "$src" "$dst"
  echo "ok      $dst -> $src"
}

# The squad is built on AgenFK: every card, gate and verdict goes through its CLI.
# A missing CLI is a warning, not a failure: the links below are still useful.
if ! command -v agenfk >/dev/null 2>&1; then
  echo "WARNING the 'agenfk' CLI is not on PATH. The squad is built on AgenFK:" >&2
  echo "        install it from https://github.com/cglab-public/agenfk before using the agents." >&2
  echo >&2
fi

mkdir -p "$CLAUDE/agents" "$CLAUDE/hooks" "$CLAUDE/skills"
rc=0
for f in "$SQUAD"/agents/*.md; do
  link "$f" "$CLAUDE/agents/$(basename "$f")" || rc=1
done
# the squad's own skills (one directory per skill) and the third-party ones in vendor/
for d in "$SQUAD"/skills/*/ "$SQUAD"/skills/vendor/*/; do
  name="$(basename "$d")"
  [ "$name" = "vendor" ] && continue
  [ -f "$d/SKILL.md" ] || continue
  link "${d%/}" "$CLAUDE/skills/$name" || rc=1
done
link "$SQUAD/CLAUDE.md" "$CLAUDE/CLAUDE.md" || rc=1
link "$SQUAD/hooks/squad-router.py" "$CLAUDE/hooks/squad-router.py" || rc=1
link "$SQUAD/hooks/squad-watch.py" "$CLAUDE/hooks/squad-watch.py" || rc=1
link "$SQUAD/hooks/squad-switch.py" "$CLAUDE/hooks/squad-switch.py" || rc=1
link "$SQUAD/hooks/squad-turn.py" "$CLAUDE/hooks/squad-turn.py" || rc=1
mkdir -p "$HOME/.local/bin"       # the merge queue is called by name: `squad-turn request`
link "$SQUAD/hooks/squad-turn.py" "$HOME/.local/bin/squad-turn" || rc=1

echo
echo "New agents and skills only show up in sessions started after this step."
echo "Hooks in settings.json (see docs/installation.md): squad-router.py on UserPromptSubmit;"
echo "squad-watch.py on PreToolUse, PostToolUse, SubagentStop, Stop and UserPromptSubmit."
exit $rc
