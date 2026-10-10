#!/usr/bin/env bash
# Save OnlyClaws Agent token (oct_…) into a local gitignored file.
#
# Preferred (from Cursor / vault MCP):
#   vault_run_with_secret OCT=EPAPER_AKI_TOKEN → bash scripts/save_oct_token.sh
#
# Or paste once:
#   OCT='oct_…' bash scripts/save_oct_token.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$ROOT/.local"
OUT="$DIR/oct_token"
mkdir -p "$DIR"
chmod 700 "$DIR"

if [[ -z "${OCT:-}" && -z "${EPAPER_AKI_TOKEN:-}" && -z "${ONLYCLAWS_OCT:-}" ]]; then
  echo "Set OCT / EPAPER_AKI_TOKEN / ONLYCLAWS_OCT in the environment first." >&2
  exit 1
fi
TOK="${OCT:-${EPAPER_AKI_TOKEN:-$ONLYCLAWS_OCT}}"
TOK="$(printf '%s' "$TOK" | tr -d '\r\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
if [[ -z "$TOK" ]]; then
  echo "empty token" >&2
  exit 1
fi
printf '%s\n' "$TOK" >"$OUT"
chmod 600 "$OUT"
echo "wrote $OUT ($(wc -c <"$OUT") bytes, mode 600)"
