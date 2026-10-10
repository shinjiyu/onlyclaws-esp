#!/usr/bin/env bash
# OnlyClaws presence MCP (stdio) for Cursor.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export JEV_CONSOLE_URL="${JEV_CONSOLE_URL:-http://127.0.0.1:8765}"
cd "$ROOT"
exec /usr/bin/python3 -m jev_servo mcp
