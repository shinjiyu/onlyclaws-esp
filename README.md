# OnlyClaws ESP · 远程 Agent 控 ESP32 平台

[English](#english) · [中文](#中文)

Remote agents drive ESP32 boards over the network — with optional on-device tools loops.  
远端 Agent 经网络控制 ESP32；需要时还可下发脚本，在设备端跑本地 tools 循环。

**Live control plane:** [https://onlyclaws.world/epaper](https://onlyclaws.world/epaper)  
**Agent API docs:** [https://onlyclaws.world/epaper/api/agent/docs](https://onlyclaws.world/epaper/api/agent/docs)

---

<a id="english"></a>
## English

### What this is

**OnlyClaws ESP** is a hybrid agent–device platform:

1. **Primary:** a remote Agent (cloud / another LLM runtime) calls HTTP tools to list devices, invoke hardware actions, push UI, and read sensors.
2. **Optional:** the same Agent can **deploy a JSON tools script** that runs a **local loop on the ESP32** (edge autonomy when the cloud is not needed every tick).
3. **Not the goal:** running a full LLM on the microcontroller.

Closest mental model: *thin ESP32 runtime + cloud control plane for Agents*, not “agent-on-device” products like ESPClaw.

### Architecture

```
Remote Agent  ──(kuroneko session)──►  OnlyClaws API
                                         │
                    invoke / deploy_script / push / events
                                         │
                                         ▼
                              ESP32 thin runtime
                         network · auth · whitelist tools
                         optional JSON script VM (loop/once)
```

### Hardware

| Board | Device ID | Notes |
|-------|-----------|--------|
| Waveshare **ESP32-S3-RLCD-4.2** | `a4cb8fdf8440` | Main agent runtime (400×300 ST7305, ES8311 audio, KEY) |
| Waveshare ESP32-S3 ePaper 3.97 | `441bf6923320` | Legacy ePaper path under `src/` |

### Repository layout

| Path | Role |
|------|------|
| `rlcd/` | RLCD firmware — agent runtime (`rlcd-agent-0.7.x`) |
| `server/` | FastAPI control plane (deployed at `/epaper`) |
| `src/` | Legacy ePaper firmware |
| `server/static/agent-api.md` | Agent function-call contract |

### Cloud defaults / multi-tenant

Private server defaults are in `rlcd/include/cloud_config.h`.

- Host: `onlyclaws.world` / path `/epaper`
- **Accounts:** kuroneko.chat login; each user only manages **their** devices
- **Device auth:** per-device token from `POST /api/devices/register` (NVS or `device_secrets.h`)
- Optional closed mode: set `EPD_ALLOWLIST` to a comma-list of emails

Override cloud host at runtime via NVS namespace `cloud` (`host` / `prefix` / `device_id` / `token`).

### Agent capabilities (session required)

Auth: **kuroneko.chat** login + email allowlist → HttpOnly cookie.

| Tool-ish API | Method | Purpose |
|--------------|--------|---------|
| List devices + sensors | `GET /api/devices` | Online, fw, temp / humidity / battery, script meta |
| Remote invoke | `POST /api/invoke` | One-shot whitelist tools on device |
| Create / deploy script | `POST /api/scripts`, `.../deploy` | Edge JSON tools loop |
| Stop / status / events | `/api/script/stop`, `/status`, `/api/events` | Lifecycle + `emit` |
| Push text / image / action | `/api/push`, `/push/image`, `/api/action` | Display + beep/wave/react |

Machine catalog: `GET /api/agent/capabilities`  
Human docs: `GET /api/agent/docs.md`

### Edge script (JSON VM)

Whitelist tools on device: `sensors.read`, `beep`, `wave`, `react`, `dialog`, `sleep`, `emit`, `if`, `stop`.

Example loop (temperature alert):

```json
{
  "mode": "loop",
  "every_ms": 10000,
  "steps": [
    {"tool": "sensors.read"},
    {
      "tool": "if",
      "when": {"meta": "temp_c", "op": "gt", "value": 35},
      "then": [
        {"tool": "beep", "freq": 1200, "ms": 80},
        {"tool": "emit", "name": "hot"}
      ]
    }
  ]
}
```

### Build & flash (RLCD)

```bash
cd rlcd
cp include/device_secrets.h.example include/device_secrets.h   # fill token / device id
pio run -e esp32-s3-rlcd-42
pio run -t upload -e esp32-s3-rlcd-42
```

Wi-Fi: hold **KEY ~1.5s** → SoftAP `RLCD-Setup-*` / `12345678` → captive portal.

### Server deploy

See `server/deploy/` and `server/config.example.env`.  
Runtime secrets (`EPD_SESSION_SECRET`, `EPD_DEVICE_TOKEN`, …) must **never** be committed.

### Security notes

- Do not commit `device_secrets.h`, `server/deploy/epaper.env`, or any tokens.
- Agents must use kuroneko session APIs — **not** the device bearer token.
- Rotate any credential that ever appeared in chat, logs, or screenshots.

---

<a id="中文"></a>
## 中文

### 这是什么

**OnlyClaws ESP** 是一套「远端 Agent ↔ ESP32」混合平台：

1. **主路径：** 远端 Agent 通过 HTTP 工具调设备——列设备、调用硬件、推送界面、读传感器。
2. **可选：** 同一 Agent 可 **下发 JSON tools 脚本**，在 ESP32 上跑 **本地循环**（边缘自治，不必每一步都回云）。
3. **不是目标：** 在单片机上跑完整 LLM / 整只 Agent。

一句话：*瘦设备运行时 + 给 Agent 用的云控制面*，不是「Agent 全塞进板子」。

### 架构

```
远端 Agent  ──(kuroneko 会话)──►  OnlyClaws API
                                    │
               invoke / 下发脚本 / 推送 / 事件
                                    │
                                    ▼
                           ESP32 瘦运行时
                      联网 · 鉴权 · 白名单工具
                      可选 JSON 脚本引擎（loop/once）
```

### 硬件

| 板子 | Device ID | 说明 |
|------|-----------|------|
| Waveshare **ESP32-S3-RLCD-4.2** | `a4cb8fdf8440` | 主运行时（400×300 ST7305、ES8311、KEY） |
| Waveshare ESP32-S3 ePaper 3.97 | `441bf6923320` | 旧墨水屏路径（`src/`） |

### 目录

| 路径 | 作用 |
|------|------|
| `rlcd/` | RLCD 固件（agent runtime，`rlcd-agent-0.7.x`） |
| `server/` | FastAPI 控制面（部署在 `/epaper`） |
| `src/` | 旧 ePaper 固件 |
| `server/static/agent-api.md` | Agent 函数调用约定 |

### 私人云 / 多租户

写在 `rlcd/include/cloud_config.h`：

- 主机：`onlyclaws.world`，路径 `/epaper`
- **账号：** kuroneko.chat 登录；每人只能管理 **自己绑定** 的设备
- **设备鉴权：** `POST /api/devices/register` 下发的 per-device token（写入 NVS 或 `device_secrets.h`）
- 可选封闭模式：设置 `EPD_ALLOWLIST` 邮箱列表

NVS `cloud` 可覆盖 `host` / `prefix` / `device_id` / `token`。

### Agent 能力（需登录会话）

鉴权：**kuroneko.chat** + 邮箱白名单 → HttpOnly Cookie。

| 能力 | 接口 | 作用 |
|------|------|------|
| 列设备 / 传感器 | `GET /api/devices` | 在线、固件、温湿度电量、脚本状态 |
| 远端调用 | `POST /api/invoke` | 一次性白名单工具 |
| 创建 / 下发脚本 | `POST /api/scripts`、`.../deploy` | 边缘 JSON tools 循环 |
| 停止 / 状态 / 事件 | `/api/script/stop`、`/status`、`/api/events` | 生命周期与 `emit` |
| 推送文案 / 图 / 动作 | `/api/push`、`/push/image`、`/api/action` | 显示 + beep/wave/react |

机器可读：`GET /api/agent/capabilities`  
人类文档：`GET /api/agent/docs.md`

### 边缘脚本（JSON 虚拟机）

设备白名单工具：`sensors.read`、`beep`、`wave`、`react`、`dialog`、`sleep`、`emit`、`if`、`stop`。

高温告警循环示例见上方 English 小节 JSON。

### 编译与烧录（RLCD）

```bash
cd rlcd
cp include/device_secrets.h.example include/device_secrets.h   # 填入 token / device id
pio run -e esp32-s3-rlcd-42
pio run -t upload -e esp32-s3-rlcd-42
```

配网：长按 **KEY 约 1.5 秒** → SoftAP `RLCD-Setup-*` / `12345678` → 打开配网页。

### 服务端部署

见 `server/deploy/` 与 `server/config.example.env`。  
`EPD_SESSION_SECRET`、`EPD_DEVICE_TOKEN` 等 **禁止提交进仓库**。

### 安全提醒

- 不要提交 `device_secrets.h`、`epaper.env`、各类 token。
- Agent 只用 kuroneko 会话接口，**不要**把设备 Bearer token 写进 Agent 工具。
- 凡在聊天、日志、截图里出现过的密钥，请立即轮换。

---

## License

Private / unlicensed unless you add a license file.  
未添加许可证文件前，默认保留所有权利。
