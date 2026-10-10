# Plugin runtime (target)

## Problem

AS-IS firmware is one binary that always exposes panel Lua (`gfx.*`), and optionally BLE/audio via ifdefs, but **capability surface is not a first-class product matrix**. Adding RoArm motor APIs into the ePaper/RLCD image wastes flash/RAM and pollutes Agent tool lists.

## Decision

Split **core** vs **capability plugins**. PlatformIO **product envs** select which plugins are compiled and registered.

```
core
  device_runtime · script_engine · wifi_nvs · cloud_http · contracts

plugins (link-time)
  panel | audio | ble_pad | sensors | arm
```

| Product env (planned names) | Plugins |
|-----------------------------|---------|
| `esp32-s3-rlcd-42` | panel + audio + ble_pad + sensors |
| `esp32-s3-epaper-397` | panel + sensors (BLE off) |
| `esp32-roarm-m2` | arm (+ sensors if useful) — **no panel/gfx** |

## Contracts

- Each plugin implements a small port on `contracts` (e.g. `PanelDisplay`, `ArmDriver`, `InvokeTool[]`).
- `script_engine` only `registerFunction`s modules that were linked.
- `device_runtime` reports `capabilities: ["panel","audio",…]` on `/status`.
- Control plane **filters** `/api/invoke` and Agent docs by that set.

## Rules (ADL)

- Plugins must not depend on other plugins (NoCross).
- Plugin out-degree ≤ K=2 → `contracts` and optionally one infra (`wifi_nvs`).
- Compose may wire many plugins.

## Migration

1. ~~Extract capability registration table~~ — `capability.h` + gated `bindApis` / invoke  
2. ~~`/status` reports `capabilities[]`; control plane filters invoke~~  
3. Move panel/audio/ble/sensors behind stronger `build_src_filter` (partially done via `OC_CAP_*`)  
4. ~~RoArm classic-ESP32 env + STS `ArmDriver`~~ — `esp32-roarm-m2`, `sts_bus`, `arm_roarm`, Lua `arm.*`  
5. ~~Agent docs / capabilities JSON advertise per-device tool map~~ — `capability_tools` + `products` in `/api/agent/capabilities`; skill/api markdown updated  

See also [`ROARM-PRODUCT.md`](./ROARM-PRODUCT.md).
