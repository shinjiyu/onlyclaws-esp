# jev_servo MCP · primitives

Cursor MCP `onlyclaws-presence` exposes **USB-level** RoArm + tip-cam tools only.

Entry: `jev_servo/run_mcp.sh` → `python3 -m jev_servo mcp`

| Tool | Moves? | Notes |
|---|---|---|
| `arm_help` | no | protocol + limits |
| `arm_connect` / `arm_disconnect` | no | QuietArmUsb session |
| `arm_feedback` | no | `q` radians ×4 |
| `arm_stream` | **yes** | `q` + `spd`; abs/step clamps |
| `arm_stop` | halt | |
| `arm_torque` | no* | `on=false` free drag |
| `arm_hold` | no | re-lock after drag |
| `cam_info` | no | Unique IDs |
| `cam_grab` | no | one JPEG; optional identify |

No `find_any` / `goto` / `record` in this MCP. Those stay as scripts under `mcp_guard/tmp/arm_frame/` if you need them.

Desk handbook (poses, shoot flow):  
`/Users/shinjiyu/Documents/mcp_guard/tmp/arm_frame/ARM_CAMERA_AGENT.md`
