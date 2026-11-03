# ADR 0009 — OCA install package + preset script pages

## Context

OnlyClaws Android (OCA, `android/`) reads its identity from `files/session.json` (`device_id`, `token`). Until now that file was pushed by hand over adb, and scripts reached the phone the same way, outside the device session. Boards already get their token inside the flash session (ADR 0008). Phones have no MAC to read before install, and Android will not apply a side file during install.

The demos (`demos/`) and the phone's Bilibili play agent (`android/scripts/bilibili-play.js`) were only reachable from the repository.

## Decision

1. **OCA devices are created by a signed-in human.** `POST /api/oca/devices` inserts a device with `kind='oca'`, a server-generated id (`oca` + 9 hex) and the caller as owner. Agent tokens (`oct_`) cannot create or package OCA devices, same rule as web flash.
2. **The install package is the stock APK plus this phone's `session.json`.** `POST /api/oca/devices/{id}/apk` mints a fresh `device_token` (the previous one stops working), writes `assets/session.json` into the unsigned base APK, runs `zipalign` and `apksigner` with the server's single OCA signing key, and returns the file. No Gradle on the server. Every download is re-signed because the content changed; the key never changes, so a new package installs over an existing OCA.
3. **The app adopts a changed packaged identity.** On start, OCA copies `assets/session.json` to `files/session.json` when it differs from the last one it applied (`files/session.seed`). A hand-written `session.json` stays until a new package arrives.
4. **`session.json` alone stays available** (`POST /api/oca/devices/{id}/session`) for development builds signed with another key.
5. **Preset scripts are a public catalog per device kind.** `/presets/esp32/` lists Lua demos; `/presets/oca/` lists phone JS (Bilibili play, empty container). Sources are copies under `server/presets/`, checked against their origins in `demos/` and `android/scripts/` by a unit test. Download is public. `POST /api/presets/{id}/deploy` (login) sends one to an owned device of the same kind: Lua through the signed script deploy, JS through `invoke` with the `js` tool.
6. **`js` is a capability tool.** Devices that report `container` accept `js`; invoke payloads to them may be up to 256 KB.

## Consequences

- The server needs JDK + Android build-tools (`apksigner`, `zipalign`), the base APK under `server/oca/`, and a keystore outside the repository. Missing pieces make the APK route answer 503; `session.json` still works.
- A downloaded APK carries a live device token in plain text; download is owner-only and each download revokes the previous package.
- Phones running a debug build signed with another key must uninstall once before installing the server package.
