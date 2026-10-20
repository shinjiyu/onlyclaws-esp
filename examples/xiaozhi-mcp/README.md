# Xiaozhi → OnlyClaws over MCP

[中文](README.zh-CN.md)

Let a [Xiaozhi](https://github.com/78/xiaozhi-esp32) voice assistant drive your OnlyClaws board:
"show the meeting time on the panel", "what's the temperature on my board?", "stop the script".

```
 you ──voice──▶ Xiaozhi device ──▶ Xiaozhi cloud (LLM)
                                        │  MCP endpoint (wss://…/mcp/?token=…)
                                        ▼
                           xiaozhi_bridge.py  (runs on your PC / server)
                                        │  HTTPS + Authorization: Bearer oct_…
                                        ▼
                           OnlyClaws control plane ──▶ your OnlyClaws board
```

The bridge dials **out** to the Xiaozhi MCP endpoint and answers JSON-RPC (`initialize`, `tools/list`,
`tools/call`) on that websocket — the same pattern as
[78/mcp-calculator](https://github.com/78/mcp-calculator) `mcp_pipe.py`. No inbound port is opened.

## Files

| File | What |
|------|------|
| `onlyclaws_mcp.py` | MCP tools → OnlyClaws REST API. Stdlib only; also works as a stdio MCP server (Cursor, Claude Desktop, `mcp_pipe.py`). |
| `xiaozhi_bridge.py` | Connects those tools to the Xiaozhi MCP endpoint, reconnects with backoff. Needs `websockets`. |
| `tests/` | Unit tests with mocked HTTP and websocket. |

## Tools

| Tool | REST call | Notes |
|------|-----------|-------|
| `onlyclaws_devices` | `GET /api/devices` | id, online, product, capabilities, `temp_c` / `humidity` / `battery_pct` from the last device status |
| `onlyclaws_show_text` | `POST /api/push` | text card (title + body ≤ 4000 chars), optional beep |
| `onlyclaws_beep` | `POST /api/action` | `{"beep": true}` |
| `onlyclaws_recent_events` | `GET /api/events` | latest `emit()` events from Lua, limit 1–50 |
| `onlyclaws_script_status` | `GET /api/script/status` | script id / state / last error |
| `onlyclaws_stop_script` | `POST /api/script/stop` | |
| `onlyclaws_deploy_lua` | `POST /api/scripts` (with `device_id`) | **off by default**, enable with `ONLYCLAWS_ALLOW_LUA=1`; max 24000 bytes |

`device_id` is optional on every tool; it falls back to `ONLYCLAWS_DEVICE_ID`, then to the server's
default (your first device). Panel tools need the `panel` capability, so they don't apply to RoArm boards.

## Setup

1. **OnlyClaws token**: sign in at <https://onlyclaws.world/console/> → *Agent tokens* → create one, copy the `oct_…` value.
   Find your device id in the same console (or call `GET /api/devices`).
2. **Xiaozhi endpoint**: in the Xiaozhi console (xiaozhi.me) open your agent's configuration and copy its
   **MCP endpoint (MCP 接入点)** URL, which looks like `wss://api.xiaozhi.me/mcp/?token=…`.
3. Run:

```bash
cd examples/xiaozhi-mcp
pip install -r requirements.txt
export XIAOZHI_MCP_ENDPOINT='wss://api.xiaozhi.me/mcp/?token=...'
export ONLYCLAWS_TOKEN='oct_...'
export ONLYCLAWS_DEVICE_ID='a4cb8fdf8440'     # optional
# export ONLYCLAWS_ALLOW_LUA=1                # optional, see Security
# export ONLYCLAWS_BASE_URL=https://your-self-hosted-server
python xiaozhi_bridge.py
```

Leave it running. When the Xiaozhi console shows the endpoint as connected, the tools are available
to your Xiaozhi device. `MCP_ENDPOINT` is accepted too, so the same env works with `mcp_pipe.py`.

To use the same tools from Cursor / Claude Desktop instead:

```json
{"mcpServers": {"onlyclaws": {"command": "python3",
  "args": ["/path/to/onlyclaws-esp/examples/xiaozhi-mcp/onlyclaws_mcp.py"],
  "env": {"ONLYCLAWS_TOKEN": "oct_...", "ONLYCLAWS_DEVICE_ID": "a4cb8fdf8440"}}}}
```

## Example voice prompts

- "在 OnlyClaws 屏幕上显示：三点开会，带电脑。" → `onlyclaws_show_text`
- "我的板子现在多少度？电量还剩多少？" → `onlyclaws_devices`
- "让板子响一下，我找不到它了。" → `onlyclaws_beep`
- "刚才板子上报了什么事件？" → `onlyclaws_recent_events`
- "脚本还在跑吗？有没有报错？" / "把脚本停掉。" → `onlyclaws_script_status` / `onlyclaws_stop_script`
- With `ONLYCLAWS_ALLOW_LUA=1`: "在板子上写一个每秒刷新的计时器。" → `onlyclaws_deploy_lua`

## Security

- Use an **Agent control token** (`oct_…`), never your password or a device token. Revoke it in the console
  if it leaks. The bridge refuses anything that doesn't start with `oct_`.
- Both the Xiaozhi endpoint URL and the `oct_` token are secrets. Keep them in env vars or a secret store,
  not in git. The bridge redacts `token=` in its logs.
- Anyone who can talk to your Xiaozhi device can call these tools. `onlyclaws_deploy_lua` lets the LLM run
  arbitrary Lua on your board (including `http.get/post` to any host), so it's off unless you set
  `ONLYCLAWS_ALLOW_LUA=1`.
- Tool results are trimmed: owner email, IP and API host are not returned to the LLM.

## Tests

```bash
cd examples/xiaozhi-mcp
python3 -m unittest discover -s tests -v
```

The tests mock `urllib` and the websocket (one test runs a real local `websockets` server playing the
Xiaozhi endpoint). They don't hit onlyclaws.world or xiaozhi.me.

## Not verified yet

- Not yet tested end to end against a live xiaozhi.me endpoint with a real board. The wire format follows
  `mcp_pipe.py`, which forwards raw JSON-RPC text frames.
- The menu path to the MCP endpoint in the Xiaozhi console may change; use whatever your console shows.
- Self-hosted `xiaozhi-esp32-server` needs its own MCP endpoint service; this bridge should work with any
  endpoint that speaks the same protocol, but that hasn't been tested.
