# Modules catalog

Target topology: **plugins → contracts (+ optional infra)**; **compose** wires implementations.  
Same O(1) rule as mcp_guard.

| id | role | path | allowed deps | notes |
|----|------|------|--------------|-------|
| contracts | contracts | `rlcd/include/panel_display.h`, `capability.h`, `arm_driver.h`, `oc_battery.h` | — | Capability flags + PanelDisplay (flush overlay) + ArmDriver ports + battery state |
| wifi_nvs | infra | `rlcd/src/wifi_store.cpp`, `wifi_ap_prov`, `api_config` | — | Provision + device identity NVS |
| cloud_http | infra | `rlcd/src/cloud_http.cpp` + `main.cpp` tlsLua | wifi_nvs | Device channel (JSON, bitmaps, model blobs); Lua channel separate |
| script_store | infra | `script_store.cpp`, `script_store_flash.cpp`, `server/script_sign.py` | — | Signed Lua on the `littlefs` partition; atomic rename, 3 versions, rollback ([SCRIPT-PERSIST.md](./SCRIPT-PERSIST.md)) |
| tenancy | infra | `server/tenancy.py` | — | Ownership + tokens |
| render | infra | `server/render.py` | — | Panel-sized bitmaps |
| ml_registry | infra | `server/ml_registry.py`, `ml_opset.py` | tenancy | Model upload + op-set check + ECDSA signing + device download ([ML-PLUGIN.md](./ML-PLUGIN.md)) |
| firmware_dist | infra | `server/firmware_catalog.py`, `server/nvs_cloud.py`, `server/firmware/`, `rlcd/scripts/package_web_flash.sh` | tenancy | Product bin catalog + login-gated provision (NVS token inject) for `/flash` ([ADR 0008](./decisions/0008-web-flash-and-color-panel.md)) |
| demos | infra | `demos/` | — | Lua apps (data), not firmware plugins |
| vision_path | infra | `vision/` | — | **通路 B** 主机：帧 → 对象/空描述/state；非 ESP |
| jev_servo_path | infra | `jev_servo/` | — | **通路 C** 主机：慢 JEV 每关节安全角区间 → 单次云 `arm.stream`；非 ESP |
| device_runtime | compose | `rlcd/src/main.cpp` | contracts, wifi_nvs, cloud_http, script_engine, script_store, plugins (wire) | Product env selects which plugins to link |
| script_engine | compose | `rlcd/src/script_engine.cpp` | contracts | Registers only compiled modules into Lua |
| control_plane | compose | `server/app.py`, `script_sign.py` | tenancy, render, ml_registry, script_store, contracts | Filters invoke by `capabilities[]`; signs Lua on deploy |
| panel | plugin | `panel_display` + ST7305 / ePaper (+ planned CO5300 AMOLED) | contracts | Compile-time W×H; color/round Lua contract for 1.75C ([AMOLED-175C-PRODUCT.md](./AMOLED-175C-PRODUCT.md)); not in RoArm product |
| audio | plugin | `audio_es8311.cpp` | contracts | Optional; omit on ePaper/RoArm if no codec |
| ble_pad | plugin | `ble_ctrl` + `http_pad` + `pad_ctrl` | contracts, wifi_nvs | D-pad + Nordic UART transport; off on ePaper |
| claude_buddy | plugin | `claude_proto.cpp` (pure) + `claude_buddy.cpp` | contracts | Claude desktop Hardware Buddy protocol + prompt card; bytes piped in by device_runtime |
| ml | plugin | `ml_engine.cpp`, `ml_manifest.cpp` (pure), vendored `lib/tflm` + `lib/esp-nn` | contracts, cloud_http | TFLite Micro op set v1; signed models cached on LittleFS; mic via hook; S3 envs only |
| sensors | plugin | `sensors.cpp` | contracts | SHTC3, battery ADC or TG28 fuel gauge; soft-fail when missing |
| arm | plugin | `arm_driver.h`, `arm_ctl.*`, `sts_bus.*`, `arm_roarm.cpp` / `arm_stub.cpp` | contracts | Feetech STS on Serial1 RX18/TX19 when `BOARD_ROARM`; host preempt via `arm_ctl` |

## AS-IS vs target

| AS-IS | Target |
|-------|--------|
| One `script_engine` registers gfx/audio/ble/sensors always | Env `build_src_filter` + capability table |
| Panel chosen only by `BOARD_PANEL_*` | Same, plus **product** envs that drop whole plugins |
| No arm code | `esp32-roarm-m2` env: `core + arm` only (`OC_PLUGIN_ARM`, no panel/audio/ble) |
| Open RoArm factory Wi-Fi JSON (external product) | Arm product: no anonymous `/js` |
