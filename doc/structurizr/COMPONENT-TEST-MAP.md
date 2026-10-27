# Component ↔ test map

Firmware and hosted control plane are mostly **device/cloud manual** today (no `tests/` tree yet).  
When unit/contract tests appear, list them here and flip `test_kind` in `requirements.json`.

| Requirement | Component | test_kind | Evidence / procedure |
|-------------|-----------|-----------|----------------------|
| REQ-CLOUD-WIRE | device_runtime | contract | `server/tests/test_device_session.py` (one socket, one in-flight message, requeue on replace). Board: session welcome, then invoke; `/pending` only if the socket is down |
| REQ-AGENT-INVOKE | control_plane | manual | `POST /api/invoke` with oct_; device executes |
| REQ-LUA-DEPLOY | script_engine | manual | Deploy snake / mimo-rl; stop; events |
| REQ-SCRIPT-PERSIST | script_store | unit | `rlcd/tests/test_script_store.py`, `server/tests/test_script_sign.py`. Board: flash the new partition table once, deploy, pull power, script resumes; bad signature is not stored |
| REQ-DEVICE-REGISTER | control_plane | manual | UI register + token rotate |
| REQ-WIFI-PROV | wifi_nvs | manual | OC-Setup portal; safe_upload keeps NVS |
| REQ-PANEL-SURFACE | panel | manual | Panel pio envs upload + flush; AMOLED when env exists |
| REQ-LUA-GFX | panel | manual | Lua draw + `gfx.W/H` layout |
| REQ-LUA-GFX-COLOR | panel | manual | AMOLED: `gfx.color`/`rgb`/`shape`/`safe_r`; see AMOLED-175C-PRODUCT.md |
| REQ-LUA-TOUCH | script_engine | manual | `input.touch` / `on_touch` only when capability `touch` |
| REQ-PANEL-AMOLED-175 | device_runtime | manual | `esp32-s3-amoled-175c` product binary |
| REQ-PANEL-FOLO-PASSPORT | device_runtime | manual | `esp32-c3-folo-passport` on Folo AI Passport |
| REQ-WEB-FLASH | control_plane | unit | `server/tests/test_firmware_catalog.py`, `server/tests/test_nvs_cloud.py`; browser `/flash` (login → MAC → provision NVS + flash) |
| REQ-AUDIO | audio | manual | beep on RLCD |
| REQ-TTS-CHILD | audio | unit | `rlcd/tests/test_host_logic.py` (girl/boy name + pitch); hear 我是童女 then 我是童男 on RLCD |
| REQ-BLE-PAD | ble_pad | manual | Pad URL + BLE dir |
| REQ-SENSORS | sensors | manual | `sensors.read` / Lua sensors() |
| REQ-BATTERY-BADGE | panel | unit | `rlcd/tests/test_host_logic.py` (label + pct curve); badge visible on RLCD |
| REQ-CLAUDE-BUDDY | claude_buddy | unit | `rlcd/tests/test_host_logic.py` (protocol); pair with Claude desktop Hardware Buddy, KEY/BOOT on a prompt |
| REQ-ML-OPSET | ml_registry | unit | `server/tests/test_ml_registry.py` (firmware/server op-set parity, real models, malformed input) |
| REQ-ML-SIGNED-DELIVERY | ml_registry | unit | `server/tests/test_ml_registry.py` (upload → signed envelope verified by openssl → blob; owner isolation) |
| REQ-ML-MANIFEST | ml | unit | `rlcd/tests/test_host_logic.py` (parser rules + server-built manifest) |
| REQ-ML-RUN | ml | manual | `ml.load` online then offline from cache; tampered blob refused; `/status` meta.ml |
| REQ-ML-KWS | ml | manual | Upload `ml/models/micro_speech`; Lua yes/no on RLCD |
| REQ-PUSH-BITMAP | control_plane | manual | push image matches panel size |
| REQ-CAPABILITIES | contracts | unit | `server/tests/test_capabilities.py` + `/status` meta.capabilities |
| REQ-PLUGIN-BUILD | device_runtime | manual | `OC_PLUGIN_*` in platformio.ini; Lua/invoke gated |
| REQ-ARM-PASSTHROUGH | arm | manual | `arm.move`/`stream`/`feedback`/`stop` invoke on `esp32-roarm-m2`; STS WritePosEx IDs 11–15 |
| REQ-ARM-LUA | arm | manual | Lua `arm.feedback` / `arm.stream` / `arm.stop` on RoArm product only |
| REQ-ARM-AUTH-WIFI | arm | manual | Anonymous joint HTTP denied (Waveshare web omitted from product image) |
| REQ-VISION-SCENE | vision_path | unit | `vision/tests/test_pipeline.py` |
| REQ-VISION-EMPTY | vision_path | unit | same |
| REQ-VISION-STATE | vision_path | unit | same |
| REQ-VISION-HOST-ONLY | vision_path | manual | RoArm/panel bins have no vision models; see VISION-PATHWAY.md |
| REQ-JEV-SERVO-TICK | jev_servo_path | manual | Slow tick + hist; see JEV-SERVO-PATHWAY.md |
| REQ-JEV-SERVO-INTERVAL | jev_servo_path | unit | `jev_servo/tests/test_interval.py` |
| REQ-JEV-SERVO-PER-JOINT | jev_servo_path | manual | Parallel per-joint JEV |
| REQ-JEV-SERVO-CLOUD-GOAL | jev_servo_path | manual | One stream/tick; no cloud traj interp |
| REQ-JEV-SERVO-HOST-ONLY | jev_servo_path | manual | No JEV in firmware; ADR 0004 |
| REQ-PRESENCE-DETECT | jev_servo_path | unit | `jev_servo/tests/test_presence_mission.py` |
| REQ-PRESENCE-TRAVERSE | jev_servo_path | unit | `jev_servo/tests/test_presence_mission.py` |
| REQ-PRESENCE-FOLLOW | jev_servo_path | unit | `jev_servo/tests/test_presence_mission.py` |
| REQ-FACE-ID | jev_servo_path | unit | `jev_servo/tests/test_face_id.py` |

## Planned automated tests (not yet files)

- Control plane: tenancy token verify (pytest)

Shipped: `server/tests/test_capabilities.py` (`tool_allowed_for_caps`); `vision/tests/test_pipeline.py`; `rlcd/tests/test_host_logic.py` (compiles `claude_proto.cpp` + `oc_battery.h` on the host; needs `pio run` once for ArduinoJson).
