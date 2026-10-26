# Product: ESP32-S3 Touch AMOLED 1.75C (badge)

Target hardware: Waveshare **ESP32-S3-Touch-AMOLED-1.75C** (round CNC badge): ESP32-S3R8, 466×466 CO5300 QSPI AMOLED, CST9217 touch, ES8311 + dual-mic ES7210, AXP2101, QMI8658.

## Status

| Layer | Status |
|-------|--------|
| Lua / Agent API contract | **Specified here** (this doc + `REQ-LUA-GFX-COLOR`, `REQ-LUA-TOUCH`, `REQ-PANEL-AMOLED-175`) |
| PlatformIO env `esp32-s3-amoled-175c` | **In tree** (audio + ml + stub panel; no TTS/BLE) |
| CO5300 `PanelDisplay` driver | **Stub only** (`Co5300AmoledStub` — PSRAM canvas + round clip; no QSPI yet) |
| Web flash | **Sole public CI SKU** (`.github/workflows/web-flash-amoled.yml`) |

## Product plugins

| Plugin | Include |
|--------|---------|
| panel | yes (color, round clip) |
| audio | yes (ES8311) |
| sensors | yes (AXP2101 battery; IMU later) |
| touch | yes (`input.touch` / `on_touch`) |
| ble_pad / claude_buddy | optional later |
| arm | **no** |
| ml | yes (S3) |

`/status` meta: `product=amoled-175c`, `capabilities` includes at least `panel`, `audio`, `sensors`, `touch`, `ml` (and `color` as a panel sub-signal — see Lua).

## Lua graphics (color + round)

Keep the existing **names** so Agents reuse draw scripts; change **color and geometry semantics** on this product only.

### Always present on panel products

`gfx.W` / `gfx.H` — **466 / 466** on this board.  
`gfx.clear` / `pixel` / `line` / `rect` / `fill_rect` / `circle` / `fill_circle` / `text` / `flush` / `qr` / `badge` / `image`  
`gfx.slow()` → **false** (AMOLED is fast).

### Color

| API | Meaning |
|-----|---------|
| `gfx.bpp` | `1` on RLCD/ePaper; **`16`** on AMOLED (RGB565 logical) |
| `gfx.color` | `false` / `true` — Agent gate |
| `gfx.rgb(r,g,b)` | → packed color for draw ops (0–255 channels) |
| `gfx.palette` | optional table `{bg, fg, accent}` as packed colors; defaults set at boot |

On **1bpp** panels, `gfx.rgb` maps to ink/background (`1`/`0`) by luminance; scripts that only pass `0`/`1` keep working on AMOLED (mapped through palette `bg`/`fg`).

Do **not** embed full RGB frames in Lua (24 KB source cap). Large art: `POST /api/bitmaps` then `gfx.image(name, x, y)` — control plane converts to panel pixels.

### Round viewport

| API | Meaning |
|-----|---------|
| `gfx.shape` | `"rect"` or `"round"` |
| `gfx.safe_r` | usable radius in px (≈ `min(W,H)/2`) |
| `gfx.in_round(x,y)` | whether `(x,y)` is inside the active circle |
| `gfx.polar(angle_deg, radius [, cx, cy])` | → `x, y` (default center = panel center) |

Driver **clips** draws to the circle. Agents should keep text and icons inside `safe_r` (leave ~8–12 px margin from the physical edge).

### Blit rules on color

- `gfx.blit` Gx 1bpp sprites still allowed (drawn with palette fg/bg).
- Full-frame 1bpp blit size is `W*H/8`; RGB full-frame blit is **not** exposed in Lua.
- `gfx.image` is the path for photographic / full-color assets.

## Lua touch

Capability: **`touch`**. New namespace (do not overload `gfx`):

| API | Meaning |
|-----|---------|
| `input.touch()` | `nil` if up / unsupported; else `{x, y, pressed=true}` (panel coords) |
| `function on_touch(x, y, phase)` | optional callback; `phase` is `"down"` \| `"move"` \| `"up"` |

Coordinates match `gfx` space and are already clipped to the round active area when possible. Multi-touch: v1 reports the primary contact only.

## Rules

- Do not ship `arm.*` in this binary.
- Do not require Xiaozhi cloud; stock Waveshare/Xiaozhi images remain recoverable via their flash tool / web install of *their* firmware.
- Existing 1bpp demos should degrade gracefully (mono via palette), not crash.

## Implementation order

1. This contract + agent-skill / capabilities docs  
2. `board_pins` + PlatformIO env + flash size (32 MB on 1.75C per Waveshare)  
3. CO5300 QSPI `PanelDisplay` + circular clip + RGB565 canvas in PSRAM  
4. CST9217 → `input.touch` / `on_touch`  
5. Package bins into `server/firmware/esp32-s3-amoled-175c/` for `/flash`
