# Component ↔ test map

Firmware and hosted control plane are mostly **device/cloud manual** today (no `tests/` tree yet).  
When unit/contract tests appear, list them here and flip `test_kind` in `requirements.json`.

| Requirement | Component | test_kind | Evidence / procedure |
|-------------|-----------|-----------|----------------------|
| REQ-CLOUD-WIRE | device_runtime | manual | Serial log `status ok`; pending delivers invoke |
| REQ-AGENT-INVOKE | control_plane | manual | `POST /api/invoke` with oct_; device executes |
| REQ-LUA-DEPLOY | script_engine | manual | Deploy snake / mimo-rl; stop; events |
| REQ-DEVICE-REGISTER | control_plane | manual | UI register + token rotate |
| REQ-WIFI-PROV | wifi_nvs | manual | OC-Setup portal; safe_upload keeps NVS |
| REQ-PANEL-SURFACE | panel | manual | Both pio envs upload + flush |
| REQ-LUA-GFX | panel | manual | Lua draw + `gfx.W/H` layout |
| REQ-AUDIO | audio | manual | beep on RLCD |
| REQ-BLE-PAD | ble_pad | manual | Pad URL + BLE dir |
| REQ-SENSORS | sensors | manual | `sensors.read` / Lua sensors() |
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

Shipped: `server/tests/test_capabilities.py` (`tool_allowed_for_caps`); `vision/tests/test_pipeline.py`.
