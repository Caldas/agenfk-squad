#!/usr/bin/env bash
# Install only the compatibility shim; never rewrite Claude's source resources.
set -euo pipefail
if (( $# )); then
  printf 'Usage: bash install.sh --pi\n' >&2
  exit 2
fi
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
agent_dir=${PI_CODING_AGENT_DIR:-"$HOME/.pi/agent"}
mkdir -p "$agent_dir/extensions" "$agent_dir/backups"
backup="$agent_dir/backups/claude-compat-$(date -u +%Y%m%dT%H%M%S)-$$"
mkdir -m 700 "$backup"
for name in claude-skills.ts usage-dashboard.ts; do
  if [[ -e "$agent_dir/extensions/$name" || -L "$agent_dir/extensions/$name" ]]; then
    cp -pL -- "$agent_dir/extensions/$name" "$backup/$name"
  fi
done
if [[ -f "$agent_dir/claude-compat.json" ]]; then cp -p -- "$agent_dir/claude-compat.json" "$backup/claude-compat.json"; fi
python3 - "$source_dir" "$agent_dir" <<'PY'
import json
from pathlib import Path
import sys
source, agent = map(Path, sys.argv[1:])
config_file = agent / 'claude-compat.json'
config = json.loads(config_file.read_text()) if config_file.exists() else {}
if not isinstance(config, dict):
    raise ValueError('Existing claude-compat.json must contain an object')
config['swarmRoot'] = str(source.parent)
for name, module in [('claude-skills.ts', 'index.ts'), ('usage-dashboard.ts', 'usage-dashboard.ts')]:
    target = agent / 'extensions' / name
    if target.is_symlink():
        target.unlink()
    target.write_text('export * from ' + json.dumps(str(source / module)) + ';\nexport { default } from ' + json.dumps(str(source / module)) + ';\n')
config_file.write_text(json.dumps(config, indent=2) + '\n')
config_file.chmod(0o600)
PY
printf 'Installed: %s/extensions/claude-skills.ts\nSource: %s\nBackup: %s\nRun /reload, then /claude-compat in Pi.\n' "$agent_dir" "$source_dir" "$backup"
