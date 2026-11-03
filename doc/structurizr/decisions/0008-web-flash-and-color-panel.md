# ADR 0008 — Browser web flash + color round panel Lua contract

## Context

Operators still flash with PlatformIO / esptool. A cheap Waveshare round AMOLED badge (1.75C) is a natural new SKU, but the tree only has 1bpp panel drivers, and onboarding still points at GitHub CLI steps.

## Decision

1. **Web flash** is a first-class control-plane surface: `/flash` uses Web Serial against signed-off product binaries under `server/firmware/<product>/`, listed by `GET /api/firmware` (**login required**). `POST /api/firmware/provision` claims the chip MAC for the signed-in user, mints a `device_token`, and returns an NVS image (cloud host/prefix/id/token, optional Wi‑Fi) flashed at `0x9000` in the same session. Packaging is a host script from PlatformIO build dirs; bins are not committed.
2. **AMOLED 1.75C** gets a documented Lua contract ([AMOLED-175C-PRODUCT.md](../AMOLED-175C-PRODUCT.md)) before the CO5300 driver: same `gfx.*` names, `gfx.color` / `gfx.bpp` / round helpers, and `input.touch` behind capability `touch`. No arm plugin on that product.

## Consequences

- HTTPS (or localhost) required for Web Serial.
- Catalog may show products as `ready: false` until packaged.
- Color panels must not break 1bpp Agent scripts that only use `0`/`1`.
- Driver work remains a follow-up; API and web flash ship first.
