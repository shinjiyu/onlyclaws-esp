# Product: FoloToy AI Passport (ESP32-C3 + ST7789)

Target hardware: **FoloToy AI Passport** — ESP32-C3, 8 MB flash, **no PSRAM**, 240×320 ST7789P3 SPI TFT, ES8311 audio, GPIO0 ADC three-key ladder, USB Serial/JTAG.

Pin facts follow FoloToy `bsp_pins.h` (AI Passport repo).

## Status

| Layer | Status |
|-------|--------|
| PlatformIO env `esp32-c3-folo-passport` | In tree |
| ST7789 `PanelDisplay` (1bpp canvas → RGB565 flush) | In tree |
| Web flash SKU | Public (`web_flash: true`) |
| ADC three-key / CW2017 battery | Soft-fail / later |
| ML / TTS / BLE | **Omitted** (no PSRAM; keep binary lean) |

## Product plugins

| Plugin | Include |
|--------|---------|
| panel | yes (240×320) |
| audio | yes (ES8311; PA always-on, `PIN_AUDIO_PA=-1`) |
| sensors | yes (I2C present; CW2017 soft-fail OK) |
| ml / tts / ble / arm | **no** |

`/status` meta: `product=folo-passport`.

## Lua

Same 1bpp `gfx.*` as RLCD/ePaper (`gfx.W=240`, `gfx.H=320`, `gfx.slow()=false`). Color `0`/`1` mapped to white/black on the color panel.

## Rules

- Do not flash S3 AMOLED / RLCD images onto this board (wrong chip).
- Factory Folo / Xiaozhi images remain recoverable via Folo web tools.
- UART0 TX conflicts with backlight GPIO21 — keep USB Serial/JTAG as console.
