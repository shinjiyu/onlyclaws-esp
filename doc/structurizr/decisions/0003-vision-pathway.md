# 3. Vision as a separate OnlyClaws pathway

## Status

Accepted

## Context

RoArm product work and early Mac-side follow loops mixed **device motor control** with **camera→text perception**.  
Operators also need a fast path that turns frames into **object descriptions** and **empty-space descriptions** for Agent / JEV-style text judges — without putting cameras or VLMs on the ESP32.

## Decision

- **Vision is pathway B**, not a firmware plugin and not part of the RoArm product binary.
- OnlyClaws has (at least) two peer pathways:
  - **Device pathway**: cloud wire + capability plugins (panel / arm / …) on ESP32
  - **Vision pathway**: host-side (Mac / SBC) frame → structured scene text; may later call device invoke, but ownership is separate
- RoArm firmware remains motor + auth wire only. No UVC, no YuNet, no “follow” in `esp32-roarm-m2`.
- Perception contract: **objects** (labelled boxes / norms) + **empties** (free-space regions), plus a **compact one-line state** for text judges. Full prose VLMs are optional slow tier, not the hot path.
- **Camera always attaches to a Vision Host**, never to the ESP:
  - **B0** lab Mac/PC + USB (current)
  - **B1/B2** wheeled: same `vision/` on an onboard SBC/Jetson; ESP only gets invoke
  - Hot-path inference stays on-vehicle; cloud gets state (or cold-path frames), not the servo loop

## Consequences

- New ADL docs: `VISION-PATHWAY.md`; reqs `REQ-VISION-*`
- Code lives under `vision/` (Python host), not `rlcd/`
- Wheeled robots add compute + cameras on the vehicle; they do **not** require putting UVC into ESP firmware
- `roarm_ident` / arm follow demos may *consume* vision, but must not redefine the product matrix
- Linking vision→arm/wheel is an **integration** choice (Agent orchestrates), not an in-firmware coupling
