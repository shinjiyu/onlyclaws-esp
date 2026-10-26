# OnlyClaws Android (OCA)

Phone-side JS container for OnlyClaws. The APK is the host (Rhino, session wire,
A2UI, transparent WebView overlay, TTS, live wallpaper). Behavior lives in a
downloaded script (`files/active.js`), pushed over the device session as a `js`
tool — same control plane as the boards.

Package: `app.onlyclaws.android` · firmware string: `oca-0.6.0` · capability: `container`

## Build

- JDK 17
- Android SDK with `platforms;android-37.0` (compileSdk 37)
- Gradle 9.3.1+ (AGP 9.1.1)

```bash
# from this directory
gradle assembleDebug
# APK: app/build/outputs/apk/debug/app-debug.apk
```

Identity is not in the APK. After install, put `files/session.json` on the device:

```json
{"device_id":"<id>","token":"<device_token>"}
```

Register the device at the console (`POST /api/devices/register`), then push scripts
with `POST /api/invoke` and a `js` tool. Do not commit tokens.

## JS surface (host objects)

| Object | Role |
|--------|------|
| `oca.log` | log line |
| `a2ui` | Basic Catalog v0.9 (`send`/`push`, `clear`, `catalog`) |
| `web` | overlay WebView (`load`/`url`/`eval`/`clear`/`touch`) |
| `tts` | `say` / `stop` + `onDone` |
| `wallpaper` | preset load/clear (`scene: "crash"` or flat color) |
| `ui` | `w`/`h`, `safe`, `keyboard` (dp) |

Script hooks: `onStart`, `onStop`, optional `onFrame`, `onAction`, `onPointer`.
