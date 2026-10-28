# OnlyClaws Android (OCA)

Phone-side JS container for OnlyClaws. The APK is the host (Rhino, session wire,
A2UI, transparent WebView overlay, TTS, live wallpaper). Behavior lives in a
downloaded script (`files/active.js`), pushed over the device session as a `js`
tool — same control plane as the boards.

Package: `app.onlyclaws.android` · firmware string: `oca-0.7.0` · capability: `container`

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
| `web` | `load` / `url` / `eval` / `clear` / `loggedIn` / `showing`. A login URL is shown in the app and closes once `SESSDATA` is set. Any other URL is loaded off-screen, muted, and does not take touches, so the phone stays usable. |
| `desk` | three screens: 运行, 配置, 日志. `desk.show({ title, status, login, running, keyReady, error, checking, open, tokens, gap, gapMin, gapMax, gapStep, prompts, prompt, custom, rows, stats, events })`. `tokens` is the running total. `open` is `运行` / `配置` / `日志` when the script wants to change screen. 开始 calls `start` after the script checks the saved key against the model. A failed check sets `error`. The gap slider reports `gap`. A preset reports its id. Custom text reports `promptText`. |
| `keys` | `get` / `set` / `has` for one private file per name, such as `deepseek`. The value is not drawn on the screen. |
| `tts` | `say` / `stop` + `onDone` |
| `wallpaper` | preset load/clear (`scene: "crash"` or flat color) |
| `ui` | `w`/`h`, `safe`, `keyboard` (dp) |
| `http` | `request({ url, method, headers, body, timeoutMs })` → `{ status, body, error, headers }` |

`http.request` blocks the script thread until the response or the timeout. Only `https`.
Connect timeout is 20s. `timeoutMs` defaults to 60000 and is clamped to 1000..120000.
`status` is 0 when no HTTP status came back. `error` is empty when a status did.
Header names are lower case. A body or response larger than 2MB is refused or cut.
The script does its own retries.

Swiping the app out of recents finishes the activity. The foreground service keeps
the script. If the phone kills that process, an exact alarm starts the service
again one second later, and `files/active.js` loads on the new process.

Script hooks: `onStart`, `onStop`, optional `onFrame`, `onAction`, `onPointer`.
