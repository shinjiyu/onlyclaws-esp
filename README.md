<div align="center">

# OnlyClaws ESP

**Give your agent a claw in the real world.**

Flash an ESP32-S3 once. After that your AI agent sends Lua over HTTP,<br>
and the board draws, plays sound, reads sensors and reports back.

[![License: MIT](https://img.shields.io/badge/license-MIT-1c1d17)](LICENSE)
![ESP32-S3](https://img.shields.io/badge/chip-ESP32--S3-e2432a)
![Firmware](https://img.shields.io/badge/firmware-agent--runtime--0.13-1c1d17)
![Lua](https://img.shields.io/badge/apps-Lua-2c2d72)
[![Agent skill](https://img.shields.io/badge/agent-skill.md-1c1d17)](https://onlyclaws.world/api/agent/skill.md)

[Website](https://onlyclaws.world/) · [Console](https://onlyclaws.world/console/) · [Agent API](https://onlyclaws.world/api/agent/docs) · [中文](README.zh-CN.md)

<img src="docs/assets/hero.png" alt="Three apps the agent deployed to the same board: Snake, a stock ticker, and a travel-frog postcard" width="100%">

<sub>Three apps, one firmware. Each one is a Lua script the agent deployed. (Rendered from the website simulator; board photos coming.)</sub>

</div>

## Why

Agents are good at deciding *what* should happen. They have no hands. OnlyClaws turns a cheap ESP32-S3 board into a peripheral an agent can program on its own:

- **Flash once.** No more rebuilding firmware for every new screen or game. Apps are Lua scripts, swapped in seconds.
- **No model on the board.** The agent thinks in the cloud; the board runs the script and reports events.
- **Safe to hand over.** The agent holds a scoped `oct_…` token, never your password. Each board has its own `device_token`.
- **Same Lua everywhere.** Panel and audio are compile-time plugins. On a bare module, `gfx.*` and `audio.*` safely do nothing.

## How it works

```mermaid
flowchart LR
    A["AI agent<br/>reads skill.md"] -- "deploy Lua<br/>oct_ token" --> C["Control plane<br/>FastAPI · MIT"]
    C -- "events" --> A
    C -- "script<br/>long-poll" --> B["ESP32-S3<br/>Lua runtime"]
    B -- "emit()" --> C
    B --- P["panel · audio · sensors · keys · HTTP"]
```

1. **Flash** the firmware for your board and register its device ID.
2. **Mint** an `oct_…` token in the console and give your agent [skill.md](https://onlyclaws.world/api/agent/skill.md).
3. The agent **deploys** scripts, the board runs them, and `emit()` events flow back.

## An app is a Lua script

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
  return 200  -- ms until the next tick
end
```

The agent deploys it with one request and reads what the board reported:

```bash
curl -X POST https://onlyclaws.world/api/scripts \
  -H "Authorization: Bearer oct_…" -H "Content-Type: application/json" \
  -d '{"name":"hello","language":"lua","mode":"loop","device_id":"YOUR_DEVICE_ID","source":"…"}'

curl https://onlyclaws.world/api/events -H "Authorization: Bearer oct_…"
```

| Module | What it gives a script |
|--------|------------------------|
| `gfx` | 1-bit drawing, text, `gfx.qr`, full-frame `gfx.blit`, named bitmaps via `gfx.image`, `gfx.slow()` for e-paper pacing |
| `audio` | `beep` and PCM playback through the ES8311 |
| `sensors()` | Temperature, humidity, battery |
| `input` | On-board KEY and BOOT buttons |
| `http` | `http.get` / `http.post` to any HTTP(S) endpoint (no device credentials attached) |
| `emit(name, table)` | Report an event to the control plane for the agent |
| `ble`, `net` | BLE controller direction, Wi-Fi status |

Full contract: [skill.md](https://onlyclaws.world/api/agent/skill.md). More apps: [`demos/`](demos/).

## Get started

Pick the path that fits.

### 1. Use the hosted console

[Apply for access](https://onlyclaws.world/apply/). Applications are reviewed by hand. Once approved you get an email with a link to set your password, then you can register boards and mint agent tokens at [onlyclaws.world/console](https://onlyclaws.world/console/).

### 2. Flash the firmware

Requires Python 3 and PlatformIO 6.

```bash
python3 -m pip install -U platformio --user
cd rlcd
cp include/device_secrets.h.example include/device_secrets.h
# Set EPD_DEVICE_ID and EPD_DEVICE_TOKEN, or leave the token empty and provision it over NVS.

pio run -e esp32-s3-rlcd-42 -t upload --upload-port /dev/cu.usbmodem*
pio device monitor -b 115200
```

To reflash without wiping the Wi-Fi credentials and token already on the board, use `bash scripts/safe_upload_keep_nvs.sh /dev/cu.usbmodem101`. Build notes and a China mirror helper are in [`rlcd/DEV.md`](rlcd/DEV.md).

### 3. Self-host the control plane

The control plane in [`server/`](server/) is a single FastAPI app with SQLite.

```bash
cd server
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp config.example.env .env   # set EPD_SESSION_SECRET, EPD_PUBLIC_BASE, EPD_AUTH_UPSTREAM ...
set -a && . ./.env && set +a
uvicorn app:app --host 127.0.0.1 --port 8787
```

Sign-in is delegated to an auth service set by `EPD_AUTH_UPSTREAM`: it must accept `POST /api/auth/login` and `POST /api/auth/register` with `{"email","password"}` and answer `{"success": true, ...}`. A systemd unit and nginx snippet are in [`server/deploy/`](server/deploy/). Point the firmware at your host in [`rlcd/include/cloud_config.h`](rlcd/include/cloud_config.h).

## Hardware

One source tree, three PlatformIO environments. Rewire any of them by editing [`rlcd/include/board_pins.h`](rlcd/include/board_pins.h); the Lua and cloud APIs stay the same.

| Environment | Board | What's compiled in |
|-------------|-------|--------------------|
| `esp32-s3-bare` | Any ESP32-S3 module with 16 MB flash and octal PSRAM | Core only: cloud channel, Lua, HTTP, events. Status goes to serial |
| `esp32-s3-rlcd-42` | Waveshare ESP32-S3-RLCD-4.2 | ST7305 400×300 reflective LCD (~140 ms/frame), ES8311 audio, sensors, BLE `OC-Snake` |
| `esp32-s3-epaper-397` | Waveshare ESP32-S3-ePaper-3.97 | 800×480 e-paper with partial refresh, ES8311 audio. BLE off to leave heap for TLS |

On e-paper, `gfx.slow()` returns true so animations can stretch frames to about 900 ms. The same script runs on both panels.

## Repository

| Path | What's there |
|------|--------------|
| [`rlcd/`](rlcd/) | Firmware. Build and flash from here |
| [`server/`](server/) | Control plane: devices, scripts, events, bitmaps, console |
| [`demos/`](demos/) | Lua apps to deploy: Snake (key, phone D-pad or HTTP controller) and a live RL-training dashboard |
| [`scripts/`](scripts/) | Host setup helpers |

<details>
<summary>Legacy tree</summary>

`src/`, `include/` and the root `platformio.ini` are the earlier e-paper-only firmware. They are kept for reference; new work goes in `rlcd/`.

</details>

## Status

Firmware line `agent-runtime-0.13.x`, with panel and audio plugins since `0.13.6`. The hosted console is invite-only while we keep costs and abuse in check. Issues and pull requests are welcome, especially new panel plugins and demo apps.

## License

Source in this repository is [MIT](LICENSE).

The `esp32-s3-epaper-397` environment links [GxEPD2](https://github.com/ZinggJM/GxEPD2) (GPL-3.0-or-later), so firmware built with that environment is distributed under GPL-3.0-or-later. The bare and RLCD environments do not link it. See [NOTICE](NOTICE).
