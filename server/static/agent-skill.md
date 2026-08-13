# OnlyClaws ESP — Agent Skill

Base: `https://onlyclaws.world/epaper`

**Agents never use kuroneko email/password.**  
A human logs into the web UI, mints an **Agent control token** (`oct_…`), and gives that token to the Agent.

## Auth

```http
Authorization: Bearer oct_...
```

- Public skill (this file): `GET /api/agent/skill.md` — no auth
- Capabilities: `GET /api/agent/capabilities` — needs token
- Full docs: `GET /api/agent/docs.md` — needs token

On `401`, ask the human to mint/rotate a token at https://onlyclaws.world/epaper — do **not** ask for their password.

## Mint (humans only)

1. Open https://onlyclaws.world/epaper and log in with kuroneko.chat
2. **Agent 控制 Token** → create (e.g. name `aki`)
3. Copy the `oct_…` value once; store in Agent secret vault
4. Revoke anytime from the same UI

## Core calls

| Action | Call |
|--------|------|
| Who am I | `GET /api/auth/me` |
| List my devices | `GET /api/devices` |
| Invoke one-shot tools | `POST /api/invoke` |
| Push text / bitmap | `POST /api/push` |
| Beep action | `POST /api/action` |
| **Deploy Lua** | `POST /api/scripts` (`language=lua`, `source` = Lua string) |
| Events from `emit()` | `GET /api/events` |

## Lua on device (full board)

Firmware exposes **graphics, PCM audio, sensors, buttons, WiFi** — not a text-only demo.

### Graphics (400×300, 1bpp)

`gfx.clear` / `pixel` / `line` / `rect` / `fill_rect` / `circle` / `fill_circle` / `text` / `blit(b64)` / `flush`  
`gfx.W`=400, `gfx.H`=300. Color `0`/`1`. Call `gfx.flush()` after draw ops.

### Audio

`audio.beep(freq, ms)` · `audio.play_pcm(b64)` (int16 LE mono @ `sample_rate()`) · `audio.pa(on)` · `audio.ready()`

### Other

`sensors()` · `emit(name, table?)` · `input.key()` / `boot()` · `net.rssi()` / `ip()` / `ssid()` · `log` / `sleep` / `stop` / `millis` · `display(l1,l2)` convenience

### Deploy example

```http
POST /api/scripts
Authorization: Bearer oct_...
Content-Type: application/json

{
  "name": "draw-demo",
  "language": "lua",
  "mode": "once",
  "device_id": "a4cb8fdf8440",
  "source": "function on_start()\n  gfx.clear(0)\n  gfx.fill_circle(200,120,50,1)\n  gfx.flush()\n  audio.beep(1000,80)\nend\n"
}
```

## Do not

- Do not call `POST /api/auth/login` with user passwords
- Do not use **device** `device_token` as the Agent credential
- Do not mint agent tokens using an existing agent token

## Device IDs

| id | Panel |
|----|--------|
| `a4cb8fdf8440` | RLCD 4.2" 400×300 (main agent runtime) |
| `441bf6923320` | ePaper 3.97" 800×480 |

Prefer `GET /api/devices` and use an **online** device you own.
