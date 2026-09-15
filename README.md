# OnlyClaws ESP · Remote Agent ↔ ESP32 Runtime

[English](#english) · [中文](#中文)

Pure **agent/device framework**: cloud control plane + on-device **Lua** runtime.  
No character UI, no on-device LLM — Agents drive hardware over the network and may deploy edge scripts.

**Live:** [https://onlyclaws.world/epaper](https://onlyclaws.world/epaper) · **Docs:** [/api/agent/docs](https://onlyclaws.world/epaper/api/agent/docs)

---

<a id="english"></a>
## English

### Model

1. Remote Agent (primary) → HTTP tools: list devices, invoke, deploy Lua, events  
2. Optional edge Lua loop on the ESP32  
3. Multi-tenant: each kuroneko user owns their devices + per-device tokens  

### Lua on device

Full board surface: **gfx** (incl. `gfx.qr`), **PCM audio**, sensors, buttons, Wi‑Fi,
**`http.get` / `http.post`**, optional **BLE pad**, and an **on-device HTTP D-pad**
at `http://<board-ip>/` (any phone browser on the same LAN).

```lua
function on_start()
  gfx.clear(0)
  gfx.fill_circle(200, 120, 50, 1)
  gfx.flush()
  audio.beep(1000, 80)
end

function on_loop()
  local d = ble.dir()  -- shared with LAN pad / BLE writers
  -- ...
  return 200
end
```

Local build: [`rlcd/DEV.md`](rlcd/DEV.md).

### Demo apps

Demos are **edge Lua applications**, not the platform itself:

| Demo | Path |
|------|------|
| Snake (KEY / LAN pad + QR / remote HTTP) | [`demos/snake/`](demos/snake/) |

Deploy a demo with `POST /api/scripts` (see demo README).

### Layout

| Path | Role |
|------|------|
| `rlcd/` | ESP32-S3-RLCD runtime (`rlcd-runtime-0.12.x`, Lua) |
| `server/` | FastAPI control plane (+ optional `/snake` phone UI helpers) |
| `demos/` | Application demos (Lua scripts + notes) |
| `src/` | Legacy ePaper firmware |

### Build

```bash
cd rlcd
cp include/device_secrets.h.example include/device_secrets.h
pio run -e esp32-s3-rlcd-42
pio run -t upload -e esp32-s3-rlcd-42
# keep NVS tokens: rlcd/scripts/safe_upload_keep_nvs.sh /dev/cu.usbmodem*
```

---

<a id="中文"></a>
## 中文

### 定位

纯框架：**远端 Agent 控板** + 可选 **设备端 Lua 脚本**。  
不做角色 UI，不在板子上跑大模型。应用 demo（如贪食蛇）在 [`demos/`](demos/) 下，与平台分离。

### 多租户

kuroneko 登录后只能管自己的设备；每台板独立 `device_token`。

### Lua

板端暴露完整能力：`gfx.*` / `gfx.qr`、`audio.*`、传感器、按键、Wi‑Fi、`http.*`、
本机控制页 `http://板IP/`、可选 BLE。详见 `/api/agent/skill.md`。

### 编译烧录

同 English「Build」一节。
