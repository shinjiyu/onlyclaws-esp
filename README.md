# OnlyClaws ESP32 Agent Platform

Remote agents control ESP32 boards over the network. Optionally deploy a JSON tools script for an on-device local loop.

## Layout

| Path | Role |
|------|------|
| `rlcd/` | ESP32-S3-RLCD-4.2 firmware (agent runtime) |
| `server/` | FastAPI control plane at `https://onlyclaws.world/epaper` |
| `src/` | Legacy ePaper firmware |

## Private cloud defaults

- Host: `onlyclaws.world` (`rlcd/include/cloud_config.h`)
- Public base: `https://onlyclaws.world/epaper`
- Auth: kuroneko.chat + allowlist
- Secrets: `rlcd/include/device_secrets.h` (gitignored), `server/deploy/epaper.env` (gitignored)

## Agent APIs (session required)

- `POST /api/invoke` — remote whitelist tools
- `POST /api/scripts` + `POST /api/scripts/{id}/deploy` — edge script
- `POST /api/script/stop`, `GET /api/script/status`, `GET /api/events`
- Docs: `/api/agent/docs.md`

## Build / flash (RLCD)

```bash
cd rlcd
pio run -e esp32-s3-rlcd-42
pio run -t upload -e esp32-s3-rlcd-42
```
