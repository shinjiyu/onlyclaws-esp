#!/usr/bin/env bash
# OnlyClaws RoArm + tip-cam primitive MCP (stdio) for Cursor.
# Tools: arm_connect/feedback/stream/stop/torque/hold + cam_info/cam_grab
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export MCP_GUARD_ROOT="${MCP_GUARD_ROOT:-$HOME/Documents/mcp_guard}"
export ARM_FRAME_DIR="${ARM_FRAME_DIR:-$MCP_GUARD_ROOT/tmp/arm_frame}"
export ARM_USB_PORT="${ARM_USB_PORT:-/dev/cu.usbserial-110}"
cd "$ROOT"
exec /usr/bin/python3 -m jev_servo mcp
