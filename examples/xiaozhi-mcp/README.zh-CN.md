# 小智通过 MCP 调用 OnlyClaws

[English](README.md)

让 [小智](https://github.com/78/xiaozhi-esp32) 语音助手直接控制你的 OnlyClaws 板子，比如“把会议时间显示到屏幕上”“板子那边现在多少度”“把脚本停掉”。

```
 你 ──语音──▶ 小智设备 ──▶ 小智云端（大模型）
                               │  MCP 接入点（wss://…/mcp/?token=…）
                               ▼
                  xiaozhi_bridge.py（跑在你的电脑或服务器上）
                               │  HTTPS + Authorization: Bearer oct_…
                               ▼
                  OnlyClaws 控制面 ──▶ 你的 OnlyClaws 板子
```

桥接程序主动**向外**连接小智的 MCP 接入点，在这条 websocket 上响应 JSON-RPC 请求（`initialize`、`tools/list`、`tools/call`）。做法和 [78/mcp-calculator](https://github.com/78/mcp-calculator) 的 `mcp_pipe.py` 一样，不需要开放入站端口。

## 文件

| 文件 | 说明 |
|------|------|
| `onlyclaws_mcp.py` | 把 MCP 工具映射到 OnlyClaws REST API。只用标准库，也可以当 stdio MCP 服务用（Cursor、Claude Desktop、`mcp_pipe.py`）。 |
| `xiaozhi_bridge.py` | 把这些工具接到小智 MCP 接入点，断线后指数退避重连。依赖 `websockets`。 |
| `tests/` | 单元测试，HTTP 和 websocket 都是 mock 的。 |

## 工具

| 工具 | REST 接口 | 说明 |
|------|-----------|------|
| `onlyclaws_devices` | `GET /api/devices` | 设备 id、在线状态、型号、能力，以及最近一次上报的 `temp_c` / `humidity` / `battery_pct` |
| `onlyclaws_show_text` | `POST /api/push` | 显示文字卡片（标题 + 正文，正文最多 4000 字），可选提示音 |
| `onlyclaws_beep` | `POST /api/action` | `{"beep": true}` |
| `onlyclaws_recent_events` | `GET /api/events` | Lua 里 `emit()` 上报的最新事件，1–50 条 |
| `onlyclaws_script_status` | `GET /api/script/status` | 脚本 id、运行状态、最近一次错误 |
| `onlyclaws_stop_script` | `POST /api/script/stop` | |
| `onlyclaws_deploy_lua` | `POST /api/scripts`（带 `device_id`） | **默认关闭**，设 `ONLYCLAWS_ALLOW_LUA=1` 才开启；最多 24000 字节 |

每个工具的 `device_id` 都可以不填，依次回退到 `ONLYCLAWS_DEVICE_ID`、服务端默认（你名下的第一块板子）。屏幕类工具需要设备有 `panel` 能力，RoArm 机械臂不适用。

## 配置

1. **OnlyClaws 令牌**：登录 <https://onlyclaws.world/console/> → *Agent 令牌* → 新建，复制 `oct_…`。设备 id 在同一个控制台里能看到（也可以调 `GET /api/devices`）。
2. **小智接入点**：在小智控制台（xiaozhi.me）打开你的智能体配置，复制 **MCP 接入点** 地址，格式类似 `wss://api.xiaozhi.me/mcp/?token=…`。
3. 运行：

```bash
cd examples/xiaozhi-mcp
pip install -r requirements.txt
export XIAOZHI_MCP_ENDPOINT='wss://api.xiaozhi.me/mcp/?token=...'
export ONLYCLAWS_TOKEN='oct_...'
export ONLYCLAWS_DEVICE_ID='a4cb8fdf8440'     # 可选
# export ONLYCLAWS_ALLOW_LUA=1                # 可选，见“安全”
# export ONLYCLAWS_BASE_URL=https://你自建的服务器
python xiaozhi_bridge.py
```

保持运行。小智控制台显示接入点已连接后，你的小智设备就能用这些工具了。也兼容 `MCP_ENDPOINT` 变量，同一套环境变量可以直接给 `mcp_pipe.py` 用。

想在 Cursor / Claude Desktop 里用同一套工具：

```json
{"mcpServers": {"onlyclaws": {"command": "python3",
  "args": ["/path/to/onlyclaws-esp/examples/xiaozhi-mcp/onlyclaws_mcp.py"],
  "env": {"ONLYCLAWS_TOKEN": "oct_...", "ONLYCLAWS_DEVICE_ID": "a4cb8fdf8440"}}}}
```

## 语音示例

- “在 OnlyClaws 屏幕上显示：三点开会，带电脑。” → `onlyclaws_show_text`
- “我的板子现在多少度？电量还剩多少？” → `onlyclaws_devices`
- “让板子响一下，我找不到它了。” → `onlyclaws_beep`
- “刚才板子上报了什么事件？” → `onlyclaws_recent_events`
- “脚本还在跑吗？有没有报错？” / “把脚本停掉。” → `onlyclaws_script_status` / `onlyclaws_stop_script`
- 开启 `ONLYCLAWS_ALLOW_LUA=1` 后：“在板子上写一个每秒刷新的计时器。” → `onlyclaws_deploy_lua`

## 安全

- 只用 **Agent 控制令牌**（`oct_…`），不要用账号密码或设备令牌。泄露了就去控制台吊销。不是 `oct_` 开头的令牌桥接程序会直接拒绝。
- 小智接入点地址和 `oct_` 令牌都是密钥，放环境变量或密钥管理里，别提交到 git。日志里的 `token=` 会被打码。
- 任何能对你的小智说话的人都能调用这些工具。`onlyclaws_deploy_lua` 等于让大模型在板子上跑任意 Lua（包括用 `http.get/post` 访问任意地址），所以默认关闭，除非设了 `ONLYCLAWS_ALLOW_LUA=1`。
- 返回给大模型的结果做了裁剪，不包含账号邮箱、IP 和 API 地址。

## 测试

```bash
cd examples/xiaozhi-mcp
python3 -m unittest discover -s tests -v
```

测试 mock 了 `urllib` 和 websocket，其中一个用例会在本地起一个真实的 `websockets` 服务来扮演小智接入点。不会访问 onlyclaws.world 或 xiaozhi.me。

## 尚未验证

- 还没有用真实的 xiaozhi.me 接入点加实体板子做端到端联调。线上协议参照 `mcp_pipe.py`，它就是原样转发 JSON-RPC 文本帧。
- 小智控制台里 MCP 接入点的入口位置可能会变，以你控制台里实际显示的为准。
- 自建的 `xiaozhi-esp32-server` 需要单独的 MCP 接入点服务。理论上只要协议一致，这个桥接就能用，但没测过。
