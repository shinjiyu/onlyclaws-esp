#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export MCP_GUARD_ROOT="${MCP_GUARD_ROOT:-$HOME/Documents/mcp_guard}"
export ARM_FRAME_DIR="${ARM_FRAME_DIR:-$MCP_GUARD_ROOT/tmp/arm_frame}"
export ARM_USB_PORT="${ARM_USB_PORT:-/dev/cu.usbserial-110}"
export ARM_MCP_HTTP_HOST="${ARM_MCP_HTTP_HOST:-127.0.0.1}"
export ARM_MCP_HTTP_PORT="${ARM_MCP_HTTP_PORT:-8787}"
export ARM_MCP_HTTP_TOKEN_FILE="${ARM_MCP_HTTP_TOKEN_FILE:-$ARM_FRAME_DIR/.arm_mcp_http_token}"
cd "$ROOT"
exec /usr/bin/python3 -m jev_servo.mcp_http
