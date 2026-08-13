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

```lua
function on_start()
  log("boot")
  emit("script_started")
end

function on_loop()
  local s = sensors()
  if s.temp_c and s.temp_c > 35 then
    beep(1200, 80)
    emit("hot", { temp = s.temp_c })
  end
  display("temp", string.format("%.1fC", s.temp_c or -1))
  return 10000  -- next delay ms (or call sleep(10000))
end
```

Whitelist APIs: `sensors`, `beep`, `emit`, `display`, `log`, `sleep`, `stop`, `millis` (also under `oc.*`).

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
| `rlcd/` | ESP32-S3-RLCD runtime (`rlcd-runtime-0.9.x`, Lua) |
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

见上方示例。白名单：`sensors` / `beep` / `emit` / `display` / `log` / `sleep` / `stop` / `millis`。

### 编译烧录

同 English「Build」一节。
