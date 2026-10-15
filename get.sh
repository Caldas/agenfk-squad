#!/bin/sh
# One-command install of agenfk-squad on Linux, WSL and macOS.
#
#   curl -fsSL https://raw.githubusercontent.com/eduardopin/agenfk-squad/main/get.sh | sh
#   curl -fsSL https://raw.githubusercontent.com/eduardopin/agenfk-squad/main/get.sh | sh -s -- --beta
#
# Options (the same as environment variables; an option wins over a variable):
#   --stable           the latest v* tag on main, or main while there is no tag (default)
#   --beta             the beta branch                       SQUAD_CHANNEL=stable|beta
#   --ref <name>       a tag, branch or commit               SQUAD_REF=<name>
#   --uninstall        remove the squad's hook entries from settings.json and the
#                      links that point into the clone; the clone stays
#   --purge            with --uninstall: delete the clone as well
# Other variables:
#   SQUAD_HOME         where the clone lives (default ~/.local/share/agenfk-squad)
#   SQUAD_REPO         where to clone from (default the GitHub repository)
#   CLAUDE_CONFIG_DIR  Claude Code's config directory (default ~/.claude)
#
# Steps: checks the prerequisites; clones, or updates the clone with fetch and
# checkout (a clone with local changes is refused, never overwritten); runs the
# clone's install.sh, which links agents, skills and hooks; registers the hooks
# from hooks/manifest.json in settings.json with scripts/squad_settings.py
# (merge, idempotent, backup first, invalid JSON is left alone). Running it
# again updates. Written for POSIX sh, because macOS ships bash 3.2.
set -eu

DEFAULT_REPO=https://github.com/eduardopin/agenfk-squad.git
GET_URL=https://raw.githubusercontent.com/eduardopin/agenfk-squad/main/get.sh

say() { printf '%s\n' "$*"; }
warn() { printf 'WARNING %s\n' "$*" >&2; }
die() { printf 'ERROR   %s\n' "$*" >&2; exit 1; }

usage() {   # $0 is "sh" under curl | sh, so the help cannot be read from this file
  cat <<EOF
Installs agenfk-squad for Claude Code: $GET_URL

  sh get.sh [--stable | --beta | --ref <tag|branch|commit>]
  sh get.sh --uninstall [--purge]

  --stable     the latest v* tag on main, or main while there is no tag (default)
  --beta       the beta branch
  --ref NAME   a tag, branch or commit
  --uninstall  remove the squad's hooks from settings.json and the links into the clone
  --purge      with --uninstall: delete the clone too

Environment: SQUAD_CHANNEL, SQUAD_REF, SQUAD_HOME (default ~/.local/share/agenfk-squad),
SQUAD_REPO, CLAUDE_CONFIG_DIR (default ~/.claude).
EOF
}

# ---------------------------------------------------------------- options
REPO="${SQUAD_REPO:-$DEFAULT_REPO}"
DIR="${SQUAD_HOME:-$HOME/.local/share/agenfk-squad}"
CLAUDE="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
CHANNEL="${SQUAD_CHANNEL:-stable}"
REF="${SQUAD_REF:-}"
ACTION=install
PURGE=0
opt_channel=""
opt_ref=""

while [ $# -gt 0 ]; do
  case $1 in
    --stable) opt_channel=stable ;;
    --beta) opt_channel=beta ;;
    --ref)
      [ $# -ge 2 ] || die "--ref needs a tag, branch or commit"
      opt_ref=$2
      shift ;;
    --ref=*) opt_ref=${1#--ref=} ;;
    --uninstall) ACTION=uninstall ;;
    --purge) PURGE=1 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option '$1' (see --help)" ;;
  esac
  shift
done

[ -n "$opt_channel" ] && [ -n "$opt_ref" ] && die "choose one: --$opt_channel or --ref"
if [ -n "$opt_ref" ]; then
  REF=$opt_ref
elif [ -n "$opt_channel" ]; then
  CHANNEL=$opt_channel
  REF=""
fi
case $CHANNEL in
  stable|beta) ;;
  *) die "unknown channel '$CHANNEL': use stable or beta, or --ref <tag|branch|commit>" ;;
esac
[ "$PURGE" = 1 ] && [ "$ACTION" != uninstall ] && die "--purge only goes with --uninstall"

case $DIR in /*) ;; *) DIR="$PWD/$DIR" ;; esac
case $CLAUDE in /*) ;; *) CLAUDE="$PWD/$CLAUDE" ;; esac

# ---------------------------------------------------------------- prerequisites
have() { command -v "$1" >/dev/null 2>&1; }

in_wsl() { grep -qi microsoft /proc/version 2>/dev/null; }

# How to get a missing tool, on this system.
how_to() {
  case $(uname -s 2>/dev/null) in
    Darwin)
      case $1 in
        git) say "run: xcode-select --install   (or, with Homebrew: brew install git)" ;;
        python3) say "run: brew install python (https://brew.sh), then make sure \$(brew --prefix)/bin comes first on PATH: the python3 that ships with macOS can be 3.9" ;;
        *) say "run: brew install $1" ;;
      esac ;;
    Linux)
      if have apt-get; then pm="sudo apt-get install -y"
      elif have dnf; then pm="sudo dnf install -y"
      elif have yum; then pm="sudo yum install -y"
      elif have pacman; then pm="sudo pacman -S"
      elif have zypper; then pm="sudo zypper install"
      elif have apk; then pm="sudo apk add"
      else pm=""
      fi
      where=""
      in_wsl && where=" inside the WSL distribution (not in Windows)"
      if [ -n "$pm" ]; then say "run$where: $pm $1"; else say "install $1 with your package manager$where"; fi
      if [ "$1" = python3 ]; then
        say "        if that python3 is older than 3.10, install a newer one (https://www.python.org/downloads/) and make it the python3 on PATH: the hooks run as 'python3'"
      fi ;;
    *) say "install $1, then run this again" ;;
  esac
}

missing=0
for tool in git curl bash; do
  if ! have "$tool"; then
    say "MISSING $tool: $(how_to "$tool")" >&2
    missing=1
  fi
done
if have python3; then
  if ! pyv=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2]); sys.exit(sys.version_info < (3, 10))' 2>/dev/null); then
    say "MISSING python3 3.10 or newer (found ${pyv:-a python3 that does not run}): $(how_to python3)" >&2
    missing=1
  fi
else
  say "MISSING python3 3.10 or newer: $(how_to python3)" >&2
  missing=1
fi
[ "$missing" = 0 ] || die "install what is missing above, then run this again. Nothing was changed."

if [ "$ACTION" = install ]; then
  have claude || warn "Claude Code ('claude') is not on PATH. The squad runs inside it: https://claude.com/claude-code"
  have agenfk || warn "the 'agenfk' CLI is not on PATH. The squad's agents call it: https://github.com/cglab-public/agenfk"
fi

# ---------------------------------------------------------------- uninstall
remove_links() {
  dir_p=$DIR
  [ -d "$DIR" ] && dir_p=$(cd "$DIR" && pwd -P)
  for root in "$CLAUDE" "$HOME/.local/bin"; do
    [ -d "$root" ] || continue
    find "$root" -maxdepth 2 -type l 2>/dev/null | while IFS= read -r link; do
      target=$(readlink "$link") || continue
      case $target in
        "$DIR"/*|"$dir_p"/*) rm -f "$link" && say "removed $link" ;;
      esac
    done
  done
}

is_clone() { [ -e "$1/.git" ] && [ -f "$1/install.sh" ] && [ -f "$1/hooks/squad-watch.py" ]; }

if [ "$ACTION" = uninstall ]; then
  if [ -f "$DIR/scripts/squad_settings.py" ] && [ -f "$DIR/hooks/manifest.json" ]; then
    python3 "$DIR/scripts/squad_settings.py" uninstall --config "$CLAUDE" --manifest "$DIR/hooks/manifest.json" \
      || die "settings.json was left as it was (see above); nothing else was removed"
  else
    warn "no installer files in $DIR, so the hook entries in $CLAUDE/settings.json were left: remove the squad-*.py entries by hand, or set SQUAD_HOME to the clone"
  fi
  remove_links
  if [ "$PURGE" = 1 ] && [ -d "$DIR" ]; then
    is_clone "$DIR" || die "$DIR does not look like an agenfk-squad clone: not deleting it"
    if [ -n "$(git -C "$DIR" status --porcelain)" ]; then
      die "$DIR has local changes: not deleting it. Save what you need, then delete it by hand"
    fi
    rm -rf "$DIR"
    say "removed $DIR"
  fi
  say
  say "agenfk-squad uninstalled."
  if [ "$PURGE" = 0 ] && [ -d "$DIR" ]; then
    say "The clone is still in $DIR (add --purge to delete it)."
  fi
  say "Sessions already open keep the old hooks until they restart: open a new Claude Code session."
  exit 0
fi

# ---------------------------------------------------------------- clone or update
if [ -e "$DIR" ] && [ ! -d "$DIR" ]; then
  die "$DIR exists and is not a directory. Move it, or set SQUAD_HOME to another place"
fi
if [ -e "$DIR/.git" ]; then
  changes=$(git -C "$DIR" status --porcelain) || die "$DIR is not a usable git clone"
  if [ -n "$changes" ]; then
    printf '%s\n' "$changes" >&2
    die "$DIR has local changes (above). The installer never overwrites them: commit or stash them (git -C \"$DIR\" stash), or move the clone away, then run this again. Nothing was changed."
  fi
  say "updating $DIR"
  git -C "$DIR" fetch --quiet --tags origin || die "could not fetch from $(git -C "$DIR" remote get-url origin 2>/dev/null || echo origin)"
elif [ -d "$DIR" ] && [ -n "$(ls -A "$DIR")" ]; then
  die "$DIR exists, is not empty and is not a git clone. Move it, or set SQUAD_HOME to another place"
else
  say "cloning $REPO into $DIR"
  mkdir -p "$(dirname "$DIR")"
  git clone --quiet "$REPO" "$DIR" || die "could not clone $REPO"
  git -C "$DIR" fetch --quiet --tags origin || true
fi
DIR=$(cd "$DIR" && pwd)

commit_of() { git -C "$DIR" rev-parse --quiet --verify "$1^{commit}" 2>/dev/null; }

if [ -n "$REF" ]; then
  commit=$(commit_of "refs/remotes/origin/$REF") || commit=$(commit_of "refs/tags/$REF") \
    || commit=$(commit_of "$REF") || die "'$REF' is not a branch, tag or commit of the repository"
  label="ref $REF"
elif [ "$CHANNEL" = beta ]; then
  commit=$(commit_of refs/remotes/origin/beta) || die "the repository has no beta branch"
  label="beta"
else
  commit_of refs/remotes/origin/main >/dev/null || die "the repository has no main branch"
  tag=$(git -C "$DIR" tag --list 'v*' --merged refs/remotes/origin/main --sort=-v:refname | sed -n 1p)
  if [ -n "$tag" ]; then
    commit=$(commit_of "refs/tags/$tag")
    label="stable ($tag)"
  else
    commit=$(commit_of refs/remotes/origin/main)
    label="stable (main: no release tag yet)"
  fi
fi

for f in install.sh scripts/squad_settings.py hooks/manifest.json; do
  git -C "$DIR" cat-file -e "$commit:$f" 2>/dev/null \
    || die "$label predates this installer (it has no $f). Choose a newer one, or install by hand: docs/installation.md"
done
git -C "$DIR" -c advice.detachedHead=false checkout --quiet --detach "$commit"
version=$(git -C "$DIR" describe --tags --always "$commit")

# ---------------------------------------------------------------- install
# settings.json first: if it cannot be edited, nothing gets linked either.
python3 "$DIR/scripts/squad_settings.py" check --config "$CLAUDE" \
  || die "nothing was installed: fix settings.json, then run this again"

links_rc=0
bash "$DIR/install.sh" || links_rc=$?

say
python3 "$DIR/scripts/squad_settings.py" install --config "$CLAUDE" --manifest "$DIR/hooks/manifest.json" \
  || die "the links are in place but the hooks were not registered (see above)"

say
say "agenfk-squad installed"
say "  channel  $label"
say "  version  $version"
say "  clone    $DIR"
say "  config   $CLAUDE"
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) warn "$HOME/.local/bin is not on PATH: add it, so that 'squad-turn' can be called by name" ;;
esac
say
say "Next: open a NEW Claude Code session. Agents, skills and hooks are read when a session starts."
say "Update: run the same command again. Remove: curl -fsSL $GET_URL | sh -s -- --uninstall"
if [ "$links_rc" != 0 ]; then
  warn "install.sh skipped some links (SKIPPED above): a real file was in the way. See docs/installation.md, 'If you already have a ~/.claude/CLAUDE.md'"
  exit 1
fi
