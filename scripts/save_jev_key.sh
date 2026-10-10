#!/usr/bin/env bash
# Write JEV_KEY from env into onlyclaws-esp/.local/jev_key (gitignored).
# Inject via vault — do not pass the key on the command line:
#   vault_run_with_secret name=JEV_KEY env_key=JEV_KEY command=bash args=[scripts/save_jev_key.sh]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$ROOT/.local"
OUT="$DIR/jev_key"
if [[ -z "${JEV_KEY:-}" ]]; then
  echo "JEV_KEY is empty. Inject from vault; do not pass on CLI." >&2
  exit 1
fi
mkdir -p "$DIR"
umask 077
printf '%s\n' "$JEV_KEY" >"$OUT"
chmod 600 "$OUT"
echo "wrote $OUT (${#JEV_KEY} chars)"
