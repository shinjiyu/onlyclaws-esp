# OnlyClaws ESP32 Agent Platform — Agent Function-Call Spec

Base URL: `https://onlyclaws.world/epaper`

**Product model:** pure agent/device framework. Remote Agents control ESP32 over the network; optionally deploy **Lua** for an on-device loop. No character UI. The full LLM does **not** run on-device.

---

## 1. Authentication

### 1.1 Agent control token (preferred for Agents)

Humans log into the web UI with kuroneko.chat, then mint an **Agent control token** (`oct_…`).

Agents call every control-plane API with:

```http
Authorization: Bearer oct_...
```

- Mint (human session cookie only): `POST /api/agent-tokens` `{"name":"aki"}`
- List: `GET /api/agent-tokens`
- Revoke: `DELETE /api/agent-tokens/{id}`
- Public skill: `GET /api/agent/skill.md` (no auth)

**Never** ask for kuroneko email/password. On `401`, ask the human to mint/rotate a token in the UI.

### 1.2 Human browser session (UI only)

`POST /api/auth/login` → HttpOnly cookie `epd_session`.  
Humans use this to manage devices and mint tokens — **not** for Agents.

### 1.3 Device bearer (firmware only)

Per-device token from `POST /api/devices/register` — ESP wire protocol only. **Not** for Agents.

---

## 2. Capability map

| Capability | API | Effect |
|------------|-----|--------|
| Public skill | `GET /api/agent/skill.md` | How Agents should auth + call |
| List **my** devices | `GET /api/devices` | Only devices owned by the token owner |
| Register / claim device | `POST /api/devices/register` | Bind `device_id`; returns `device_token` once |
| Rotate device token | `POST /api/devices/{id}/rotate-token` | New firmware bearer; old invalid |
| Remote invoke tools | `POST /api/invoke` | One-shot whitelist tools on **your** device |
| Create Lua script | `POST /api/scripts` | Store Lua source (`language=lua`) |
| Deploy Lua script | `POST /api/scripts/{id}/deploy` | Device runs `on_loop` / once |
| Stop script | `POST /api/script/stop` | Stop edge loop |
| Script status | `GET /api/script/status` | Runtime + device-reported state |
| Device events | `GET /api/events` | `emit` from Lua |
| Push text / image | `POST /api/push`, `/api/push/image` | Optional bitmap / status text |
| Device actions | `POST /api/action` | beep (and legacy action flags) |
| Agent docs | `GET /api/agent/docs.md` | This contract |
| Capabilities JSON | `GET /api/agent/capabilities` | Machine catalog |

Known device IDs:

| id | Panel |
|----|--------|
| `a4cb8fdf8440` | RLCD 4.2" 400×300 (agent runtime) |
| `441bf6923320` | ePaper 3.97" 800×480 |

---

## 3. Remote invoke (primary)

`POST /api/invoke`

```json
{
  "device_id": "a4cb8fdf8440",
  "tools": [
    {"tool": "sensors.read"},
    {"tool": "beep", "freq": 1000, "ms": 100},
    {"tool": "display", "title": "ping", "line2": "ok"},
    {"tool": "gfx.clear", "color": 0},
    {"tool": "gfx.flush"}
  ]
}
```

Invoke tools: `sensors.read`, `beep`, `display`, `emit`, `gfx.clear`, `gfx.flush`, `play_pcm` (`b64`).
Prefer **Lua deploy** for pixel drawing and multi-step logic.

---

## 4. Deploy edge Lua (optional local loop)

### 4.1 Create + deploy

`POST /api/scripts`

```json
{
  "name": "hot-alert",
  "language": "lua",
  "mode": "loop",
  "every_ms": 10000,
  "device_id": "a4cb8fdf8440",
  "source": "function on_start()\n  emit('script_started')\nend\n\nfunction on_loop()\n  local s = sensors()\n  if s.temp_c and s.temp_c > 35 then\n    beep(1200, 80)\n    emit('hot', { temp = s.temp_c })\n  end\n  return 10000\nend\n"
}
```

- `source` must be a **Lua string** (JSON tools DSL is retired)
- `mode`: `once` | `loop`
- `every_ms`: default delay between `on_loop` when the function does not return a delay / call `sleep`

Also: `POST /api/scripts/{id}/deploy`, `POST /api/script/stop`, `GET /api/script/status`, `GET /api/events`

### 4.2 Lua API (full board surface)

Color: `0` = off / white plane, `1` = on / black. Display is **400×300** 1bpp (`gfx.W` / `gfx.H`).

#### Sensors / control

| API | Notes |
|-----|------|
| `sensors()` | `{temp_c, humidity, battery_v, battery_pct}` when available |
| `emit(name, table?)` | POST event to cloud |
| `log(...)` | serial |
| `sleep(ms)` | cooperative delay (≤60s) |
| `stop()` | end script |
| `millis()` | uptime ms |
| `display(line1, line2?)` | convenience two-line status + flush |

#### Graphics (`gfx.*` or `gfx_*`)

| API | Notes |
|-----|------|
| `gfx.W` / `gfx.H` | 400 / 300 |
| `gfx.clear(color?)` | fill screen |
| `gfx.pixel(x,y,color?)` | |
| `gfx.line(x0,y0,x1,y1,color?)` | |
| `gfx.rect(x,y,w,h,color?)` | |
| `gfx.fill_rect(x,y,w,h,color?)` | |
| `gfx.circle(x,y,r,color?)` | |
| `gfx.fill_circle(x,y,r,color?)` | |
| `gfx.text(x,y,str,color?)` | FreeMonoBold 12pt |
| `gfx.blit(b64)` | full-frame MONO_HLSB 15000 bytes, base64 |
| `gfx.flush()` | push framebuffer to panel |

Drawing is buffered — call `gfx.flush()` after changes (except `display()` / `gfx.blit` which flush).

#### Audio (`audio.*`)

| API | Notes |
|-----|------|
| `audio.ready()` | ES8311 ready |
| `audio.sample_rate()` | e.g. 16000 |
| `audio.pa(on)` | speaker amp |
| `audio.beep(freq, ms)` | square wave (≤5s) |
| `audio.play_pcm(b64)` | int16 LE mono PCM, base64; max ~2s @ 16 kHz |

#### Input / net

| API | Notes |
|-----|------|
| `input.key()` / `key()` | KEY button held |
| `input.boot()` / `boot()` | BOOT held |
| `net.rssi()` / `wifi_rssi()` | |
| `net.ip()` / `wifi_ip()` | |
| `net.ssid()` / `wifi_ssid()` | |

Same APIs also under `oc.*` where registered. Lifecycle: optional `on_start` / `setup`, then `on_loop` / `loop`.

Example — draw a cat face and beep:

```lua
function on_start()
  gfx.clear(0)
  gfx.fill_circle(200, 120, 60, 1)
  gfx.fill_circle(170, 100, 8, 0)
  gfx.fill_circle(230, 100, 8, 0)
  gfx.fill_circle(200, 140, 12, 0)
  gfx.flush()
  audio.beep(880, 80)
end
```

---

## 5. Display push (secondary UX)

### 5.1 `push_text` — `POST /api/push`

```json
{
  "device_id": "a4cb8fdf8440",
  "title": "Hello",
  "body": "对话框内容",
  "beep": true,
  "wave": false,
  "react": true
}
```

### 5.2 `push_image` — `POST /api/push/image` (multipart)

### 5.3 `device_action` — `POST /api/action`

Cues without new bitmap.

---

## 6. Device wire protocol

```
Authorization: Bearer <EPD_DEVICE_TOKEN>
```

- `GET .../pending` — next message (`bitmap`|`action`|`script`|`invoke`|`script_stop`)
- `GET .../asset/{name}.bin` — framebuffer
- `POST .../ack`
- `POST .../status` — heartbeat; `meta` includes `script_id` / `script_state`
- `POST .../events` — script `emit` sink

Firmware defaults: host `onlyclaws.world`, path `/epaper` (`rlcd/include/cloud_config.h`).  
NVS namespace `cloud` can override `host` / `prefix` / `device_id`.

---

## 7. Removed

| Former API | Status |
|------------|--------|
| Voice upload / list | **410 Gone** |

---

## 8. Suggested agent tool wrappers

```text
tool onlyclaws_list_devices()
tool onlyclaws_invoke(device_id, tools)
tool onlyclaws_create_script(name, source, device_id?)
tool onlyclaws_deploy_script(script_id, device_id?, mode?, every_ms?)
tool onlyclaws_stop_script(device_id)
tool onlyclaws_script_status(device_id)
tool onlyclaws_list_events(device_id?, limit=50)
tool onlyclaws_push_text(...)
tool onlyclaws_action(...)
```

Auth: `Authorization: Bearer oct_...` on every call.  
Error shape: `{ "success": false, "message": "..." }` — HTTP 401/403/400.

---

## 9. Ops notes

- RLCD poll ~2.5s when online
- Prefer `invoke` for one-shots; deploy `loop` scripts only when edge autonomy is needed
- Chinese text for cards is **server-rendered**; script `dialog` is ASCII/short title only
- Public OpenAPI UI disabled; use `/api/agent/skill.md` + `/api/agent/capabilities`
- Agents must not use passwords; humans mint `oct_` tokens in the web UI
