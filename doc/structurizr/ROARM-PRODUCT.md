# RoArm product

## Hardware (RoArm-M2)

| Item | Value |
|------|-------|
| MCU | Classic ESP32 (`esp32dev`) env `esp32-roarm-m2` |
| Servo bus | Feetech STS @ 1 Mbps, `Serial1` GPIO **RX18 / TX19** |
| IDs | base 11, shoulder drive/driven 12/13, elbow 14, hand 15 |
| Middle | 2047 / 4096 steps |
| Driver | `sts_bus` + `arm_roarm` (`ArmDriver` name `roarm-m2-sts`) |
| Panel | Headless 8×8 stub — no gfx/audio/ble in this product image |

## Intent

Keep **OnlyClaws device wire** (token, pending, invoke, optional Lua) on the Waveshare RoArm driver ESP32, **without** shipping panel/gfx into that binary.  
Do **not** leave factory anonymous Wi-Fi JSON control open.

## Shape

```
Agent / Mac
  -- oct_invoke --> control_plane
                         |
                    pending queue
                         |
              RoArm agent-runtime (core + arm plugin)
                         |
              ArmDriver (STS WritePosEx / ReadPos, limits)
                         |
                      servos
```

## Two control paths

| Path | Use | Goes through Lua? |
|------|-----|-------------------|
| **Passthrough invoke** `arm.move` / `stream` / `feedback` / `stop` | Fast authenticated joint control | No (`arm.feedback` also emits `arm.feedback` event with `q`) |
| **Lua `arm.*`** | Slow orchestration, missions | Yes (`arm.feedback` / `stream` / `move` / `stop` / `name`) |

Shared servo lock (`arm_ctl`): mutex around STS ops; cloud invoke sets **host preempt** so Lua `arm.stream`/`move` return false until script stop/reload. `arm.feedback` / `arm.stop` still work. Lua sees `arm.preempted()`.

## Security

- STA to owner Wi-Fi; **no** open `RoArm-M2` AP joint API (factory Waveshare web not compiled in).
- Factory Waveshare firmware remains recoverable via official flash tool / open example — see Waveshare wiki.
- USB serial may stay as authenticated or debug-only hinter; not a public anonymous control plane.

## Non-goals

- Do not flash RLCD/ePaper panel stack onto the arm board.
- Do not run the full LLM on-device.
- Do **not** put cameras, YuNet/YOLO, follow/search, or JEV loops into this product — vision is **pathway B** ([`VISION-PATHWAY.md`](./VISION-PATHWAY.md)); JEV servo is **pathway C** ([`JEV-SERVO-PATHWAY.md`](./JEV-SERVO-PATHWAY.md)). Host may invoke `arm.*` via cloud.

## Requirements

`REQ-ARM-PASSTHROUGH`, `REQ-ARM-LUA`, `REQ-ARM-AUTH-WIFI`, plus shared `REQ-CLOUD-WIRE` / `REQ-PLUGIN-BUILD` / `REQ-CAPABILITIES`.

## Rollback

Arm product firmware is a **new** image. Stock Waveshare firmware can be restored with their ESP32 download tool if needed.
