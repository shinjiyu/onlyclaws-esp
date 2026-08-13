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

API (session cookie, not agent token):

- `POST /api/agent-tokens` `{"name":"aki"}`
- `GET /api/agent-tokens`
- `DELETE /api/agent-tokens/{id}`

## Core calls

All require `Authorization: Bearer oct_…`.

| Action | Call |
|--------|------|
| Who am I | `GET /api/auth/me` |
| List my devices | `GET /api/devices` |
| Invoke tools | `POST /api/invoke` |
| Push text card | `POST /api/push` |
| Beep / wave / react | `POST /api/action` |
| Deploy edge script | `POST /api/scripts` (+ optional deploy) |
| Events | `GET /api/events` |

### Invoke example

```http
POST /api/invoke
Authorization: Bearer oct_...
Content-Type: application/json

{
  "device_id": "a4cb8fdf8440",
  "tools": [
    {"tool": "sensors.read"},
    {"tool": "beep", "freq": 1000, "ms": 80}
  ]
}
```

### Push example

```http
POST /api/push
Authorization: Bearer oct_...
Content-Type: application/json

{
  "device_id": "a4cb8fdf8440",
  "title": "Aki",
  "body": "hello from agent",
  "beep": true
}
```

## Device IDs (panels)

| id | Panel |
|----|--------|
| `a4cb8fdf8440` | RLCD 4.2" 400×300 (main agent runtime) |
| `441bf6923320` | ePaper 3.97" 800×480 |

Prefer `GET /api/devices` and use an **online** device you own.

## Do not

- Do not call `POST /api/auth/login` with user passwords
- Do not use **device** `device_token` (firmware wire auth) as the Agent credential
- Do not mint new agent tokens using an existing agent token (blocked server-side)

## Edge scripts (optional)

Whitelist on device: `sensors.read`, `beep`, `wave`, `react`, `dialog`, `sleep`, `emit`, `if`, `stop`.  
See `/api/agent/docs.md` for JSON VM examples.
