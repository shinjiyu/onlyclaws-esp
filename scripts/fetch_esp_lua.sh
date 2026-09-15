#!/usr/bin/env bash
# Fetch EspLuaEngine into rlcd/lib (PlatformIO local lib, avoids git:// during pio run).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/rlcd/lib/EspLuaEngine"
URL="${ESPLUA_URL:-https://github.com/luc-github/EspLuaEngine.git}"
rm -rf "$DEST"
git clone --depth 1 "$URL" "$DEST"
rm -rf "$DEST/.git"
echo "OK -> $DEST"
