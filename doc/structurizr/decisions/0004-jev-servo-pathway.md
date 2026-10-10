# 4. JEV servo loop as pathway C

## Status

Accepted

## Context

Pathway B compresses frames into text suitable for JEV. Operators want a **slow closed loop** that steers RoArm joints from scene + goal without putting images or LLM judges on the ESP32, and without treating HTTPS invoke as a trajectory bus.

Early ideas mixed (1) fixed-rate perception queues, (2) per-call snap APIs, and (3) cloud-side multi-sample interpolation. Cloud interpolation is a poor motion clock; denser cloud `arm.stream` calls are worse than on-device slew/lerp.

## Decision

- **Pathway C — JEV servo** is a host-side loop, peer to A (device) and B (vision):
  - **B** supplies `SceneDesc.state` (snap/latest); no raw frames in JEV `state`
  - **C** runs a **slow** decision period `T_dec` (order 5–15 s)
  - Each tick, **each joint is judged independently** (parallel JEV `choice` calls)
  - The action is a **safe angle interval** `[lo, hi]` per joint (via discrete choice → interval map). Any `q` inside the interval is acceptable; the command waypoint defaults to the midpoint unless already inside
  - **Cloud carries goals, not trajectories**: at most one `arm.stream(q*, spd)` per tick (skip if all joints already in range)
  - Motion between ticks is **servo speed / future ESP `T_move` interpolation**, never host→cloud dense waypoint spam
- Not a firmware plugin; not part of the RoArm product matrix. Optional later: ESP timed lerp still reached by a **single** invoke payload
- Local serial motion remains an optional hot path, not the default C contract

## Consequences

- ADL: `JEV-SERVO-PATHWAY.md`; reqs `REQ-JEV-SERVO-*`; graph node `jev_servo_path`
- Implementation planned under `jev_servo/` on the host; consumes `vision/`, invokes device pathway tools
- Vision pathway docs note C as a consumer; RoArm firmware stays motor + auth wire only
