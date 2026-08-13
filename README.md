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

Full board surface (not a text demo): **gfx**, **PCM audio**, sensors, buttons, Wi‑Fi.

```lua
function on_start()
  gfx.clear(0)
  gfx.fill_circle(200, 120, 50, 1)
  gfx.flush()
  audio.beep(1000, 80)
  -- audio.play_pcm(b64_int16_le) for real samples
end

function on_loop()
  local s = sensors()
  if s.temp_c and s.temp_c > 35 then
    emit("hot", { temp = s.temp_c })
  end
  return 10000
end
```

APIs: `gfx.*` (pixel/line/rect/circle/text/blit/flush, 400×300 1bpp) · `audio.beep` / `play_pcm` / `pa` · `sensors` · `emit` · `input.key`/`boot` · `net.rssi`/`ip`/`ssid` · `log`/`sleep`/`stop`/`millis` · `display` (two-line helper). Also under `oc.*`.

Deploy:

```http
POST /api/scripts
{
  "name": "hot-alert",
  "language": "lua",
  "mode": "loop",
  "every_ms": 10000,
  "device_id": "a4cb8fdf8440",
  "source": "function on_loop() ... end"
}
```

### Layout

| Path | Role |
|------|------|
| `rlcd/` | ESP32-S3-RLCD runtime (`rlcd-runtime-0.10.x`, Lua) |
| `server/` | FastAPI control plane |
| `src/` | Legacy ePaper firmware |

### Build

```bash
cd rlcd
cp include/device_secrets.h.example include/device_secrets.h
pio run -e esp32-s3-rlcd-42
pio run -t upload -e esp32-s3-rlcd-42
```

---

<a id="中文"></a>
## 中文

### 定位

纯框架：**远端 Agent 控板** + 可选 **设备端 Lua 脚本**。  
不做角色 UI，不在板子上跑大模型。

### 多租户

kuroneko 登录后只能管自己的设备；每台板独立 `device_token`。

### Lua

板端暴露完整能力：`gfx.*` 像素绘图、`audio.play_pcm` / `beep`、传感器、按键、Wi‑Fi。详见 `/api/agent/skill.md`。

### 编译烧录

同 English「Build」一节。
