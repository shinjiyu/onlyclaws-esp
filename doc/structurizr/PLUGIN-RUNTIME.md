# Plugin runtime (target)

## Problem

AS-IS firmware is one binary that always exposes panel Lua (`gfx.*`), and optionally BLE/audio via ifdefs, but **capability surface is not a first-class product matrix**. Adding RoArm motor APIs into the ePaper/RLCD image wastes flash/RAM and pollutes Agent tool lists.

## Decision

Split **core** vs **capability plugins**. PlatformIO **product envs** select which plugins are compiled and registered.

```
core
  device_runtime · script_engine · wifi_nvs · cloud_http · contracts

plugins (link-time)
  panel | audio | ble_pad | claude_buddy | sensors | ml | arm
```

| Product env | Plugins (`OC_PLUGIN_*`) |
|-------------|-------------------------|
| `esp32-s3-bare` | core + ml (`ml.run` only, no mic) |
| `esp32-s3-rlcd-42` | panel + audio + ble_pad + claude_buddy + sensors + ml |
| `esp32-s3-epaper-397` | panel + audio + sensors + ml (BLE off) |
| `esp32-roarm-m2` | arm — **no panel/gfx** |

## Contracts

- Each plugin implements a small port on `contracts` (e.g. `PanelDisplay`, `ArmDriver`, `InvokeTool[]`).
- `script_engine`: panel and bare builds register every non-arm module (missing hardware no-ops, so one script runs anywhere); arm builds register only core + `arm.*`.
- `device_runtime` reports `capabilities: ["panel","audio",…]` on `/status`.
- `claude_buddy` rides on `OC_PLUGIN_BLE`: it never touches NimBLE; `device_runtime` pipes `ble_pad`'s Nordic UART bytes into it ([ADR 0005](./decisions/0005-claude-buddy-ble.md)).
- The panel draws the battery badge as a flush overlay; `device_runtime` feeds it from `sensors`.
- `ml` runs Agent-delivered TFLite models (signed manifest, fixed op set); `device_runtime` hands it the mic as a hook ([ADR 0006](./decisions/0006-ml-models-as-data.md), [ML-PLUGIN.md](./ML-PLUGIN.md)). C++17 + vendored TFLM, so S3 envs only.
- Control plane **filters** `/api/invoke` and Agent docs by that set.

## Rules (ADL)

- Plugins must not depend on other plugins (NoCross).
- Plugin out-degree ≤ K=2 → `contracts` and optionally one infra (`wifi_nvs`).
- Compose may wire many plugins.

## Migration

1. ~~Extract capability registration table~~ — `capability.h` + gated `bindApis` / invoke  
2. ~~`/status` reports `capabilities[]`; control plane filters invoke~~  
3. ~~Move panel/audio/ble behind compile-time plugins~~ — `OC_PLUGIN_*` in `oc_features.h`, `panel_plugin` / `audio_plugin` stubs  
4. ~~RoArm classic-ESP32 env + STS `ArmDriver`~~ — `esp32-roarm-m2`, `sts_bus`, `arm_roarm`, Lua `arm.*`  
5. ~~Agent docs / capabilities JSON advertise per-device tool map~~ — `capability_tools` + `products` in `/api/agent/capabilities`; skill/api markdown updated  

See also [`ROARM-PRODUCT.md`](./ROARM-PRODUCT.md).
