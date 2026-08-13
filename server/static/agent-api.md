# OnlyClaws ESP32 Agent Platform — Agent Function-Call Spec

Base URL: `https://onlyclaws.world/epaper`  
Auth for **control-plane** APIs: **kuroneko.chat** session. Each user only sees **their own** devices.  
Auth for **device** APIs: **per-device** bearer from `POST /api/devices/register` (shown once).  
Optional lock: `EPD_ALLOWLIST` comma-list; `*` or empty = any kuroneko user.

**Product model:** remote Agents drive devices over the network. Optionally deploy a JSON tools script that runs a **local loop on the ESP32** (edge autonomy). The full LLM does **not** run on-device.

---

## 1. Authentication (kuroneko.chat)

### 1.1 Login

`POST /api/auth/login`

```json
{ "email": "you@example.com", "password": "..." }
```

- Proxies to `https://kuroneko.chat/api/auth/login`
- On success sets HttpOnly cookie `epd_session` (`Path=/epaper`, `Secure`, `SameSite=Lax`)
- Optional: if server `EPD_ALLOWLIST` is a comma-list, email must be listed (`*` / empty = open)

### 1.2 Session check / logout

- `GET /api/auth/me`
- `POST /api/auth/logout`

### 1.3 Calling as an agent

1. Login once; store `Set-Cookie`
2. Send cookie on every request
3. Treat `401` as re-login
4. Do **not** embed device bearer tokens in agent tools

---

## 2. Capability map

| Capability | API | Effect |
|------------|-----|--------|
| List **my** devices | `GET /api/devices` | Only devices owned by the session |
| Register / claim device | `POST /api/devices/register` | Bind `device_id`; returns `device_token` once |
| Rotate token | `POST /api/devices/{id}/rotate-token` | New bearer; old invalid |
| Remote invoke tools | `POST /api/invoke` | One-shot whitelist tools on **your** device |
| Create script | `POST /api/scripts` | Store JSON tools script |
| Deploy script | `POST /api/scripts/{id}/deploy` | Device runs local loop / once |
| Stop script | `POST /api/script/stop` | Stop edge loop |
| Script status | `GET /api/script/status` | Runtime + device-reported state |
| Device events | `GET /api/events` | `emit` from scripts |
| Push text / image | `POST /api/push`, `/api/push/image` | Bitmap card + optional cues |
| Device actions | `POST /api/action` | beep/wave/react without card |
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
    {"tool": "wave"}
  ]
}
```

Shorthand single tool: `{ "device_id": "...", "tool": { "tool": "react" } }`

Queued as message `type=invoke`; device executes on next poll (~2.5s).

---

## 4. Deploy edge script (optional local loop)

### 4.1 Create

`POST /api/scripts`

```json
{
  "name": "hot-alert",
  "device_id": "a4cb8fdf8440",
  "source": {
    "version": 1,
    "mode": "loop",
    "every_ms": 10000,
    "on_start": [
      {"tool": "emit", "name": "script_started"}
    ],
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
}
```

If `device_id` is set, the script is also deployed immediately.

### 4.2 Deploy / stop / status

- `POST /api/scripts/{id}/deploy` `{ "device_id", "mode?", "every_ms?", "max_iters?" }`
- `POST /api/script/stop` `{ "device_id" }`
- `GET /api/script/status?device_id=`
- `GET /api/events?device_id=&limit=50`

### 4.3 Script format (device VM)

| Field | Meaning |
|-------|---------|
| `mode` | `once` (default) or `loop` |
| `every_ms` | Delay between loop iterations (min 200) |
| `max_iters` | 0 = forever; else stop after N loops |
| `on_start` | Steps run once after load |
| `steps` | Steps each iteration |

### 4.4 Whitelist tools

| tool | args | notes |
|------|------|-------|
| `sensors.read` | — | Updates temp/humidity/battery vars |
| `beep` | `freq`, `ms` | Speaker; `ms` capped at 2000 |
| `wave` / `react` | — | Character cues |
| `dialog` | `title` | Bubble text |
| `sleep` | `ms` | Cooperative delay (≤60s) |
| `emit` | `name`, `data?` | POST event to cloud |
| `if` | `when`/`cond`, `then`, `else?` | `when`: `{meta, op, value}` |
| `stop` | — | End script |

`meta` keys: `temp_c`, `humidity`, `battery_v`, `battery_pct`  
`op`: `gt` `gte` `lt` `lte` `eq` `neq`

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
tool onlyclaws_login(email, password)
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

Error shape: `{ "success": false, "message": "..." }` — HTTP 401/403/400.

---

## 9. Ops notes

- RLCD poll ~2.5s when online
- Prefer `invoke` for one-shots; deploy `loop` scripts only when edge autonomy is needed
- Chinese text for cards is **server-rendered**; script `dialog` is ASCII/short title only
- Public OpenAPI UI disabled; use this doc + `/api/agent/capabilities`
