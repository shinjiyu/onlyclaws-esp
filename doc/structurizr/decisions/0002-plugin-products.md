# 2. Capability plugins and RoArm as a product env

## Status

Accepted

## Context

Panel firmwares should not carry motor APIs; RoArm firmwares should not carry `gfx.*`.  
Compile-time `BOARD_PANEL_*` already swaps display backends but does not define a general plugin matrix.

## Decision

- Treat **panel / audio / ble_pad / sensors / arm** as ADL **plugins** (O(1) deps to contracts/infra only).
- Product = PlatformIO env that links a **subset** of plugins on top of shared core (device wire + Lua shell).
- RoArm product includes **motor passthrough invoke** (no Lua) plus optional Lua `arm.*`.
- Disable anonymous factory-style local joint HTTP on the RoArm product.

## Consequences

- `REQ-PLUGIN-BUILD`, `REQ-CAPABILITIES`, `REQ-ARM-*` gate the work.
- Control plane must learn `capabilities[]` filtering.
- Restoring Waveshare stock firmware remains an escape hatch; OnlyClaws RoArm image is a separate artifact.
