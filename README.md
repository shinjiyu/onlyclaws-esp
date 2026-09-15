# OnlyClaws ESP

远端 Agent 控板 + ESP32 端 Lua 运行时。  
云端下发指令 / 热部署脚本，板子负责显示、按键、音频、本机控制页等能力。

**线上：** [onlyclaws.world/epaper](https://onlyclaws.world/epaper)  
**Agent 文档：** [/api/agent/docs](https://onlyclaws.world/epaper/api/agent/docs) · [skill.md](https://onlyclaws.world/epaper/api/agent/skill.md)

[English](#english) · [中文](#中文)

---

<a id="中文"></a>
## 中文

### 定位

这是一套 **设备框架**，不是某个具体 App：

| 做什么 | 不做什么 |
|--------|----------|
| 多租户设备注册与鉴权 | 板端角色 UI / 大模型 |
| 远端 invoke、事件、脚本热部署 | 把 demo 写死进固件 |
| 统一 Lua 运行时 + 屏幕适配层 | 每块屏各写一套业务逻辑 |

应用（例如贪食蛇）放在 [`demos/`](demos/)，通过云端 `POST /api/scripts` 下发即可。

### 架构

```
┌─────────────┐     HTTPS      ┌──────────────────┐
│ 远端 Agent  │ ─────────────► │ onlyclaws.world  │
│ / 控制台    │ ◄───────────── │ 控制面 + 消息队列 │
└─────────────┘   status/event └────────┬─────────┘
                                        │ poll / deploy
                               ┌────────▼─────────┐
                               │  ESP32 运行时     │
                               │  Lua · gfx · pad  │
                               └────────┬─────────┘
                                        │
                    ┌───────────────────┼───────────────────┐
                    ▼                   ▼                   ▼
              RLCD 400×300         ePaper 800×480      手机浏览器
              ST7305 快刷          墨水屏局刷          http://板IP/
```

1. **远端 Agent（主路径）**：列设备、invoke、部署 Lua、收事件  
2. **板端可选 loop**：`on_start` / `on_loop`，适合游戏、仪表、本地交互  
3. **多租户**：kuroneko 用户只管自己的设备；每台板独立 `device_token`

### 支持硬件

同一套 `rlcd/` 固件，用 PlatformIO **环境**选屏（`PanelDisplay` 适配层）：

| 环境 | 板子 | 分辨率 | 说明 |
|------|------|--------|------|
| `esp32-s3-rlcd-42` | Waveshare ESP32-S3-RLCD-4.2 | 400×300 | 反射 LCD，刷新快；可开 BLE |
| `esp32-s3-epaper-397` | Waveshare ESP32-S3-ePaper-3.97 | 800×480 | 墨水屏，局刷为主；默认关 BLE 保 TLS 堆 |

固件版本前缀：`agent-runtime-0.13.x`。

**墨水屏注意：**

- 全刷会黑白闪一下，属面板特性；运行时以局刷为主，避免游戏中频繁全刷  
- 刷新慢，demo 通过 `gfx.slow()` 自动拉长步进（约 900 ms）；RLCD 仍约 140 ms  
- 两块屏的 Lua / 本机控制页 / 云端接口一致，业务脚本可共用

### 板端能力（Lua）

```lua
function on_start()
  gfx.clear(0)
  gfx.fill_circle(gfx.width() // 2, 120, 40, 1)
  gfx.flush()
  audio.beep(1000, 80)
end

function on_loop()
  local d = ble.dir()   -- 与本机 HTTP 控制页共用方向状态
  if gfx.slow and gfx.slow() then
    return 900          -- ePaper
  end
  return 140            -- RLCD
end
```

常用表面：

| 模块 | 能力 |
|------|------|
| `gfx.*` | 点线圆、文字、`gfx.qr`、`gfx.flush`、`gfx.slow()` |
| `audio.*` | beep / PCM |
| `input.*` | KEY / BOOT |
| `http.*` | 任意 HTTP(S)，**不**带设备 Bearer |
| 本机 Pad | `http://<板IP>/` 方向键页（同 Wi‑Fi 手机浏览器） |
| BLE（可选） | RLCD 上 `OC-Snake` 外设，与 Pad 共享方向 |

完整约定见线上 `/api/agent/skill.md`。

### 目录

| 路径 | 作用 |
|------|------|
| [`rlcd/`](rlcd/) | 统一 Agent 运行时（Lua + Pad + PanelDisplay） |
| [`rlcd/DEV.md`](rlcd/DEV.md) | 本机构建 / 烧录细节 |
| [`demos/`](demos/) | 应用 demo（热部署 Lua） |
| [`demos/snake/`](demos/snake/) | 贪食蛇（KEY / 本机 Pad+QR / 远端 HTTP） |
| [`server/`](server/) | 可选本地 FastAPI 辅助（如 `/snake`） |
| [`src/`](src/) | 旧版仅 ePaper 固件（已由统一运行时替代） |

### 快速开始

```bash
# 依赖（macOS 示例）
python3 -m pip install -U platformio --user
export PATH="$HOME/Library/Python/3.9/bin:$PATH"

cd rlcd
cp include/device_secrets.h.example include/device_secrets.h
# 填写 EPD_DEVICE_ID / EPD_DEVICE_TOKEN（或烧录后走 NVS）

# RLCD
pio run -e esp32-s3-rlcd-42 -t upload --upload-port /dev/cu.usbmodem*

# ePaper 3.97"
pio run -e esp32-s3-epaper-397 -t upload --upload-port /dev/cu.usbmodem*

# 保留 NVS 里的 token / Wi‑Fi（推荐）
bash scripts/safe_upload_keep_nvs.sh /dev/cu.usbmodem101
pio device monitor -b 115200
```

国内镜像见 [`scripts/install_from_cn_mirrors.sh`](scripts/install_from_cn_mirrors.sh)。

### Demo：贪食蛇

推荐 [`demos/snake/lua/lan_pad.lua`](demos/snake/lua/lan_pad.lua)：板子自己开 HTTP 方向键页，延迟低、任意浏览器可用。

```bash
# 使用 Agent Token（oct_…）热部署
curl -sS -X POST https://onlyclaws.world/epaper/api/scripts \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(python3 - <<'PY'
import json
src = open("demos/snake/lua/lan_pad.lua").read()
print(json.dumps({
  "name": "snake-lan",
  "language": "lua",
  "mode": "loop",
  "every_ms": 140,
  "device_id": "你的设备ID",
  "source": src,
}))
PY
)"
```

手机连同一 Wi‑Fi，打开屏上 / Game Over 二维码里的 `http://板IP/`。  
更多变体见 [`demos/snake/README.md`](demos/snake/README.md)。

### 相关链接

- 控制台：https://onlyclaws.world/epaper  
- Agent OpenAPI：https://onlyclaws.world/epaper/api/agent/docs  
- 本仓库固件开发说明：[`rlcd/DEV.md`](rlcd/DEV.md)

---

<a id="english"></a>
## English

**OnlyClaws ESP** is a remote-agent + on-device **Lua** framework (no character UI, no on-device LLM).

- **Cloud:** [onlyclaws.world/epaper](https://onlyclaws.world/epaper) · [Agent docs](https://onlyclaws.world/epaper/api/agent/docs)
- **Runtime:** `rlcd/` (`agent-runtime-0.13.x`) with `PanelDisplay`
  - `esp32-s3-rlcd-42` — ST7305 400×300  
  - `esp32-s3-epaper-397` — GxEPD2 800×480 (partial refresh; BLE off by default)
- **Demos:** [`demos/snake/`](demos/snake/) (deploy via `POST /api/scripts`)
- **Build:** see Chinese「快速开始」or [`rlcd/DEV.md`](rlcd/DEV.md)

```bash
cd rlcd
cp include/device_secrets.h.example include/device_secrets.h
pio run -e esp32-s3-rlcd-42 -t upload
# or: pio run -e esp32-s3-epaper-397 -t upload
```
