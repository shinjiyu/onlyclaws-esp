# 5. Claude Hardware Buddy over BLE, battery badge by default

## Status

Accepted

## Context

OnlyClaws devices reach Agents over Wi-Fi through the control plane. Anthropic's Claude desktop apps (Cowork, Claude Code) expose a maker BLE API, [Hardware Buddy](https://github.com/anthropics/claude-desktop-buddy/blob/main/REFERENCE.md): Nordic UART Service, one JSON object per line. The desktop pushes session heartbeats, turn events and permission prompts; the device answers commands and can approve or deny a pending tool call. It is local, needs no token, and only works while the desktop app is in developer mode.

The RLCD product already runs NimBLE for the D-pad and has a screen and two buttons, so it can be a Claude desk companion with little extra code.

Separately, the default screen never showed battery level, although the RLCD measures it (GPIO4, 1/3 divider) and the ePaper board has a TG28 (renamed AXP2101) fuel gauge on I2C.

## Decision

- **New plugin `claude_buddy`** (`OC_HAS_BLE` builds only). It knows the Hardware Buddy JSON, not BLE:
  - `claude_proto` is pure C++ (ArduinoJson + std) and host-tested.
  - `ble_pad` adds the Nordic UART service next to the D-pad service and exposes raw bytes in/out.
  - `device_runtime` pipes those bytes into `claude_buddy` and hands it the `PanelDisplay` contract, a beep hook and the battery state. No plugin→plugin edge.
- BLE builds advertise as `Claude-OC-XXXX` (the desktop picker filters on the `Claude` prefix). Only the UART UUID is advertised; the D-pad service stays in GATT.
- UART writes require an encrypted, authenticated link (LE Secure Connections, DisplayOnly). The passkey is drawn on the panel.
- A pending permission prompt takes the screen: the canvas is saved, a card is drawn, Lua ticks pause. KEY approves once, BOOT denies. The canvas is restored when the prompt is answered or disappears. Scripts may call `claude.takeover(false)` to handle prompts themselves via `claude.state()` / `claude.allow(id)` / `claude.deny(id)`.
- Folder push is declined (`ok:false`); assets keep coming from the control plane.
- **Battery badge**: `PanelDisplay::flush()` runs a framework overlay before the panel driver. The panel plugin draws a top-right badge from an `OcBattery` value that `device_runtime` refreshes every 30 s from `sensors`. `gfx.badge(false)` hides it until the next script load.

## Consequences

- Reqs `REQ-CLAUDE-BUDDY`, `REQ-BATTERY-BADGE`; graph node `claude_buddy`; contracts gain `oc_battery.h` and the flush overlay hook.
- The BLE name changes from `OC-Snake` to `Claude-OC-XXXX`; D-pad clients must match by name prefix, not by advertised service.
- ePaper keeps BLE off (heap), so it gets the battery badge but not Claude Buddy.
- The protocol is a developer-mode API Anthropic does not officially support; it may change without notice.
