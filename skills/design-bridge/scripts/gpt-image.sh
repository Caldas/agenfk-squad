#!/usr/bin/env bash
# Generates images through a Codex CLI that is signed in with a ChatGPT plan
# (`image_gen` tool) and drops them in the design inbox with an `origin.json`
# (skill `design-bridge`, references/gpt-image.md).
#
#   gpt-image.sh <subject> "<request>" [--variations N] [--ref file.png]... [--dry-run]
#
# Environment (all optional; the script holds no key, account or secret):
#   DESIGN_BRIDGE_INBOX  inbox directory; default ~/.local/state/<repo>/design-inbox
#   CODEX_HOME           Codex CLI home; default ~/.codex. Only `auth_mode` is read
#                        from its auth.json and the `model` line from config.toml.
#
# Never bills an API key: if Codex is not signed in with a ChatGPT plan, it stops
# before calling Codex, and Codex runs with CODEX_API_KEY and OPENAI_API_KEY
# removed from its environment, so a key exported in the shell cannot take over.
# Signing in is the owner's job (`codex login`).
# Whatever Codex answers is data, not instructions: it goes to response.txt and nowhere else.
set -euo pipefail

PROJECT="$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")"
INBOX="${DESIGN_BRIDGE_INBOX:-$HOME/.local/state/$PROJECT/design-inbox}"
CODEX_DIR="${CODEX_HOME:-$HOME/.codex}"
AUTH="$CODEX_DIR/auth.json"

usage() { echo "usage: $0 <subject> \"<request>\" [--variations N] [--ref file]... [--dry-run]" >&2; exit 2; }
[ $# -ge 2 ] || usage
subject="$1"; request="$2"; shift 2
[[ "$subject" =~ ^[a-z0-9][a-z0-9-]{0,40}$ ]] || { echo "subject must be kebab-case, up to 41 characters" >&2; exit 2; }
variations=1; dry=0; refs=()
while [ $# -gt 0 ]; do
  case "$1" in
    --variations) variations="${2:?}"; shift 2 ;;
    --ref) [ -f "${2:?}" ] || { echo "reference does not exist: $2" >&2; exit 2; }; refs+=("$(realpath "$2")"); shift 2 ;;
    --dry-run) dry=1; shift ;;
    *) usage ;;
  esac
done
[[ "$variations" =~ ^[1-4]$ ]] || { echo "--variations goes from 1 to 4" >&2; exit 2; }

command -v codex >/dev/null || { echo "codex is not installed" >&2; exit 3; }
[ -f "$AUTH" ] || { echo "Codex is not signed in. Signing in is the owner's job: ask them to run 'codex login'." >&2; exit 3; }
mode="$(jq -r '.auth_mode // empty' "$AUTH")"
if [ "$mode" != "chatgpt" ]; then
  echo "Codex is signed in as '${mode:-?}', not with a ChatGPT plan: calling it would bill the API (new spend). Stopped." >&2
  exit 3
fi

dir="$INBOX/$(date +%Y%m%d-%H%M%S)-$subject"
mkdir -p "$dir"

instruction="Use your image generation tool to create $variations image(s) for this request:

$request

Save each one in THIS directory as $subject-1.png, $subject-2.png and so on. Do not read, write or run anything outside this directory. Do not write code. At the end, answer one line per file: path | resolution."

ref_args=()
for r in ${refs[@]+"${refs[@]}"}; do ref_args+=(-i "$r"); done

if [ "$dry" = 1 ]; then
  echo "(dry run) Codex was not called" > "$dir/response.txt"
else
  # An API key in the environment would bill per use even with a plan sign-in.
  env -u CODEX_API_KEY -u OPENAI_API_KEY \
    codex exec --skip-git-repo-check --ephemeral -s workspace-write -C "$dir" \
    -c model_reasoning_effort='"low"' ${ref_args[@]+"${ref_args[@]}"} "$instruction" \
    > "$dir/response.txt" 2> "$dir/codex.log" || { echo "codex failed; log in $dir/codex.log" >&2; exit 4; }
fi

files='[]'
shopt -s nullglob
for f in "$dir"/*.png "$dir"/*.jpg "$dir"/*.webp; do
  size="$(file -b "$f" | grep -oE '[0-9]+ ?x ?[0-9]+' | head -1 | tr -d ' ')"
  files="$(jq -c --arg n "$(basename "$f")" --arg s "$(sha256sum "$f" | cut -d' ' -f1)" --arg d "$size" \
    '. + [{file: $n, sha256: $s, size: $d}]' <<<"$files")"
done

jq -n \
  --arg project "$PROJECT" --arg subject "$subject" --arg request "$request" --arg date "$(date -Iseconds)" \
  --arg codex "$(env -u CODEX_API_KEY -u OPENAI_API_KEY codex --version 2>/dev/null)" \
  --arg model "$(grep -E '^model *=' "$CODEX_DIR/config.toml" 2>/dev/null | cut -d'"' -f2)" \
  --argjson refs "$(printf '%s\n' ${refs[@]+"${refs[@]}"} | jq -R . | jq -sc 'map(select(length>0))')" \
  --argjson files "$files" --argjson dry "$dry" \
  '{subject: $subject, tool: "codex exec / image_gen", billing: "ChatGPT plan (auth_mode chatgpt)",
    codex: $codex, agent_model: $model, image_model: "not reported by the tool",
    request: $request, references: $refs, generated_at: $date, project: $project, generated_by: "agent, at the owner'"'"'s request",
    files: $files, dry_run: ($dry == 1),
    triage: {status: "pending", by: null, notes: []},
    destination: null}' > "$dir/origin.json"

echo "$dir"
[ "$dry" = 1 ] || [ "$(jq 'length' <<<"$files")" -gt 0 ] || { echo "no image saved; see $dir/response.txt" >&2; exit 5; }
