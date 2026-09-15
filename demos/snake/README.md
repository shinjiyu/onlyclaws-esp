# Demo: Snake

Edge Lua game on OnlyClaws ESP (RLCD 400×300). Shows how Agents deploy a loop
script that uses board APIs — not part of the core control plane.

## Variants

| Script | Input | Needs firmware |
|--------|--------|----------------|
| [`lua/key.lua`](lua/key.lua) | KEY = turn left | any Lua runtime |
| [`lua/lan_pad.lua`](lua/lan_pad.lua) | Phone browser → `http://<board-ip>/` | `rlcd-runtime ≥ 0.12.2` (on-device HTTP pad + `gfx.qr`) |
| [`lua/remote_http.lua`](lua/remote_http.lua) | Poll external `CTRL/dir` | `http.get` (`≥ 0.11`) |

**Recommended:** `lan_pad.lua` — board serves the D-pad locally (low latency, any browser).

## Deploy (cloud)

```bash
# With Agent token (oct_…):
curl -sS -X POST https://onlyclaws.world/epaper/api/scripts \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(python3 - <<'PY'
import json
src=open("demos/snake/lua/lan_pad.lua").read()
print(json.dumps({
  "name": "snake-lan",
  "language": "lua",
  "mode": "loop",
  "every_ms": 140,
  "device_id": "a4cb8fdf8440",
  "source": src,
}))
PY
)"
```

Phone (same Wi‑Fi as the board): open the URL shown on screen / Game Over QR  
(e.g. `http://192.168.101.26/`).

## Optional: PC-side control host

[`tools/lan_ctrl_server.py`](tools/lan_ctrl_server.py) is a **separate** tiny server for
`remote_http.lua` experiments. Prefer on-device pad for the main demo.

## Platform APIs used

- `gfx.*`, `gfx.qr` · `audio.beep` · `input.key` · `net.ip` / `net.ssid`
- On-device pad: firmware `http_pad` + shared `pad_ctrl` (also BLE optional)
