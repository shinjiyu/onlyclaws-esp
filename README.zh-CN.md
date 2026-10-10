<div align="center">

# OnlyClaws ESP

**给你的 Agent 一只伸进现实世界的爪子。**

ESP32 只烧一次固件。之后 AI Agent 通过 HTTP 下发 Lua，<br>
板子负责画图、发声、动机械臂、读传感器，再把结果报回来。

[![License: MIT](https://img.shields.io/badge/license-MIT-1c1d17)](LICENSE)
![ESP32-S3](https://img.shields.io/badge/chip-ESP32--S3-e2432a)
![Firmware](https://img.shields.io/badge/firmware-agent--runtime--0.16-1c1d17)
![Lua](https://img.shields.io/badge/apps-Lua-2c2d72)
[![Agent skill](https://img.shields.io/badge/agent-skill.md-1c1d17)](https://onlyclaws.world/api/agent/skill.md)

[主页](https://onlyclaws.world/) · [控制台](https://onlyclaws.world/console/) · [Agent API](https://onlyclaws.world/api/agent/docs) · [English](README.md)

<img src="docs/assets/hero.png" alt="Agent 部署到同一块板上的三个应用：贪食蛇、股票看板、旅行青蛙明信片" width="100%">

<sub>同一份固件，三个应用，每个都是 Agent 下发的一段 Lua。（图为主页模拟器渲染，实物照片稍后补上。）</sub>

</div>

## 为什么

Agent 擅长决定"该做什么"，但它没有手。OnlyClaws 把一块便宜的 ESP32-S3 板变成 Agent 能自己编程的外设：

- **只烧一次。** 换个界面、加个游戏不用重编固件。应用就是 Lua 脚本，几秒内热替换。
- **板上不跑模型。** Agent 在云端思考，板子只执行脚本、回报事件。
- **放心交给 Agent。** Agent 拿的是有范围的 `oct_…` 令牌，碰不到你的密码。每块板有自己的 `device_token`。
- **同一份 Lua 到处跑。** 屏和音频是编译期插件。裸模组上 `gfx.*`、`audio.*` 安全地什么都不做。
- **能管屏，也能管机械臂。** 同一套运行时驱动微雪 RoArm-M2 桌面机械臂：Agent 用同一个令牌、同一条队列读关节角度、下发姿态。

## 工作原理

```mermaid
flowchart LR
    A["AI Agent<br/>读 skill.md"] -- "下发 Lua<br/>oct_ 令牌" --> C["控制面<br/>FastAPI · MIT"]
    C -- "事件" --> A
    C -- "脚本<br/>长轮询" --> B["ESP32-S3<br/>Lua 运行时"]
    B -- "emit()" --> C
    B --- P["屏 · 音频 · 机械臂 · 传感器 · 按键 · HTTP"]
```

1. **烧录**对应板子的固件，在控制台登记设备 ID。
2. 在控制台**签发** `oct_…` 令牌，把 [skill.md](https://onlyclaws.world/api/agent/skill.md) 交给 Agent。
3. Agent **下发**脚本，板子执行，`emit()` 的事件回流给 Agent。

## 一个应用就是一段 Lua

```lua
function on_start()
  gfx.clear(0)
  gfx.text(12, 30, "hello from my agent", 1)
  gfx.fill_circle(gfx.W // 2, 150, 40, 1)
  gfx.flush()
  audio.beep(1000, 80)
end

function on_loop()
  local s = sensors()
  if input.key() then
    emit("pressed", { temp = s.temp_c })
  end
  return 200  -- 多少毫秒后再跑下一次
end
```

Agent 一个请求部署，再读板子回报的事件：

```bash
curl -X POST https://onlyclaws.world/api/scripts \
  -H "Authorization: Bearer oct_…" -H "Content-Type: application/json" \
  -d '{"name":"hello","language":"lua","mode":"loop","device_id":"YOUR_DEVICE_ID","source":"…"}'

curl https://onlyclaws.world/api/events -H "Authorization: Bearer oct_…"
```

| 模块 | 脚本能用它做什么 |
|------|------------------|
| `gfx` | 1-bit 绘图、文字、`gfx.qr`、整帧 `gfx.blit`、`gfx.image` 画具名位图、`gfx.slow()` 判断电子纸节奏 |
| `audio` | 通过 ES8311 `beep` 和播放 PCM |
| `sensors()` | 温度、湿度、电量 |
| `input` | 板载 KEY 和 BOOT 按键 |
| `http` | `http.get` / `http.post` 访问任意 HTTP(S) 地址（不带设备凭据） |
| `emit(name, table)` | 向控制面上报事件，供 Agent 读取 |
| `ble`、`net` | BLE 手柄方向、Wi-Fi 状态 |
| `arm` | 仅机械臂固件：`arm.feedback()` 读关节角度，`arm.move` / `arm.stream` 按弧度下发姿态，`arm.stop()` 停住 |

机械臂板跑的也是同样的脚本。下面这段读出当前姿态、上报，再把臂竖直收起：

```lua
function on_start()
  local p = arm.feedback()          -- {base, shoulder, elbow, hand, q={...}}，单位弧度
  emit("pose", { q = p.q })
  arm.move({ base = 0, shoulder = 0, elbow = 3.05, hand = 3.14, spd = 200 })
end
```

要低延迟控制时，Agent 可以绕过 Lua，直接用 `POST /api/invoke` 发一次性的 `arm.move` / `arm.feedback` / `arm.stop`。板子会上报 `capabilities[]`（例如 `["core","arm"]`），控制面会拒绝板子不具备的指令。

完整约定见 [skill.md](https://onlyclaws.world/api/agent/skill.md)，更多应用见 [`demos/`](demos/)。

## 开始使用

按需选一条路。

### 1. 用托管控制台

[提交申请](https://onlyclaws.world/apply/)，人工审核。通过后会收到邮件，里面有设置密码的链接，然后就能在 [onlyclaws.world/console](https://onlyclaws.world/console/) 登记板子、签发 Agent 令牌。

### 2. 烧录固件

需要 Python 3 和 PlatformIO 6。

```bash
python3 -m pip install -U platformio --user
cd rlcd
cp include/device_secrets.h.example include/device_secrets.h
# 填 EPD_DEVICE_ID 和 EPD_DEVICE_TOKEN；令牌也可以留空，之后写进 NVS。

pio run -e esp32-s3-rlcd-42 -t upload --upload-port /dev/cu.usbmodem*
pio device monitor -b 115200
```

想保留板上已有的 Wi-Fi 和令牌再刷，用 `bash scripts/safe_upload_keep_nvs.sh /dev/cu.usbmodem101`。编译说明和国内镜像脚本见 [`rlcd/DEV.md`](rlcd/DEV.md)。

### 3. 自建控制面

[`server/`](server/) 里的控制面是一个 FastAPI 应用加 SQLite。

```bash
cd server
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp config.example.env .env   # 设置 EPD_SESSION_SECRET、EPD_PUBLIC_BASE、EPD_AUTH_UPSTREAM 等
set -a && . ./.env && set +a
uvicorn app:app --host 127.0.0.1 --port 8787
```

登录委托给 `EPD_AUTH_UPSTREAM` 指向的认证服务：它要接受 `POST /api/auth/login` 和 `POST /api/auth/register`，请求体为 `{"email","password"}`，成功时返回 `{"success": true, ...}`。systemd 单元和 nginx 配置片段在 [`server/deploy/`](server/deploy/)。固件连哪个主机在 [`rlcd/include/cloud_config.h`](rlcd/include/cloud_config.h) 里改。

## 硬件

一套源码，四个 PlatformIO 环境。改接线只需编辑 [`rlcd/include/board_pins.h`](rlcd/include/board_pins.h)，Lua 和云端 API 不变。

| 环境 | 板子 | 编进去的内容 |
|------|------|--------------|
| `esp32-s3-bare` | 任意 16 MB flash + octal PSRAM 的 ESP32-S3 模组 | 只有核心：云通道、Lua、HTTP、事件。状态打到串口 |
| `esp32-s3-rlcd-42` | 微雪 ESP32-S3-RLCD-4.2 | ST7305 400×300 反射屏（约 140 ms/帧）、ES8311 音频、传感器、BLE `OC-Snake` |
| `esp32-s3-epaper-397` | 微雪 ESP32-S3-ePaper-3.97 | 800×480 电子纸局刷、ES8311 音频。BLE 关闭，给 TLS 留堆 |
| `esp32-roarm-m2` | 微雪 RoArm-M2 驱动板（经典 ESP32） | 飞特 STS 舵机总线（GPIO18/19），Lua 和 invoke 都能用 `arm.*`。无屏、无音频、无 BLE，出厂那套开放 Wi-Fi 关节接口不编进去 |

电子纸上 `gfx.slow()` 返回 true，动画可以把一帧拉长到约 900 ms。同一段脚本两块屏都能跑。机械臂产品说明见 [`doc/structurizr/ROARM-PRODUCT.md`](doc/structurizr/ROARM-PRODUCT.md)。

## 仓库结构

| 路径 | 内容 |
|------|------|
| [`rlcd/`](rlcd/) | 固件，在这里编译烧录 |
| [`server/`](server/) | 控制面：设备、脚本、事件、位图、控制台 |
| [`demos/`](demos/) | 可部署的 Lua 应用：贪食蛇（按键、手机方向键或 HTTP 控制）、实时 RL 训练看板、Wi-Fi 质量监控、机械臂姿态保持 |
| [`jev_servo/`](jev_servo/) | 主机侧机械臂控制：正运动学、USB 和云端两种通道、MCP 服务、网页控制台 |
| [`vision/`](vision/) | 主机侧摄像头管线（YuNet、SFace、YOLOv8n），Agent 可以把识别结果转成机械臂动作。模型用 `bash vision/scripts/fetch_models.sh` 下载 |
| [`doc/structurizr/`](doc/structurizr/) | 架构模型和产品说明（`python scripts/adl_check.py`） |
| [`scripts/`](scripts/) | 主机环境辅助脚本 |

<details>
<summary>旧代码</summary>

`src/`、`include/` 和根目录 `platformio.ini` 是早期只支持电子纸的固件，留作参考，新开发都在 `rlcd/`。

</details>

## 状态

固件版本线 `agent-runtime-0.16.x`：屏和音频插件从 `0.13.6` 开始，RoArm-M2 机械臂插件从 `0.16.0` 开始。为控制成本和滥用，托管控制台目前邀请制。欢迎提 Issue 和 PR，尤其是新的屏幕插件和示例应用。

## 许可

本仓库源码使用 [MIT](LICENSE)。

`esp32-s3-epaper-397` 环境链接了 [GxEPD2](https://github.com/ZinggJM/GxEPD2)（GPL-3.0-or-later），用这个环境编出的固件按 GPL-3.0-or-later 分发。bare 和 RLCD 环境不链接它。详见 [NOTICE](NOTICE)。
