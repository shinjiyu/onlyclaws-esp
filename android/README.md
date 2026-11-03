# OnlyClaws Android (OCA)

Phone-side JS container for OnlyClaws. The APK is the host (V8 via Javet, local
agent, transparent WebView overlay, TTS, live wallpaper). Behavior lives in
`files/active.js`. By default the phone runs **download-only** (ADR 0010): it
pulls OCA presets from `https://onlyclaws.world/epaper/api/presets` over HTTPS
and does **not** hold a device session for remote control. Opt in to「接受远控」
in settings when you need console `js` invoke / preset deploy over the wire.

Package: `app.onlyclaws.android` · firmware string: `oca-0.9.0` · capability: `container`

## Build

- JDK 17
- Android SDK with `platforms;android-37.0` (compileSdk 37)
- Gradle 9.3.1+ (AGP 9.1.1)

```bash
# from this directory
gradle assembleDebug
# APK: app/build/outputs/apk/debug/app-debug.apk
```

Identity lives in `files/session.json`:

```json
{"device_id":"<id>","token":"<device_token>"}
```

**Install package from the console (normal path).** Console → OCA phones → Create,
then Download APK. The server takes the unsigned release APK, adds
`assets/session.json` for that phone, then zipaligns and signs it with one fixed key
(`server/oca_pack.py`, ADR 0009). On start, `SessionSeed` copies the packaged file to
`files/session.json` when it differs from the last one applied, so a newer package
takes over and a hand-placed file survives otherwise. Each download issues a new
token; the previous package stops connecting.

Publish the base APK for the server:

```bash
bash android/scripts/package_oca_base.sh   # → server/oca/oca-base.apk + VERSION
```

**Dev build.** A debug build carries no `assets/session.json`. Download
`session.json` from the same console row and put it in `files/` with
`adb … run-as app.onlyclaws.android`. Debug and server packages have different
signatures: switching between them needs one uninstall, which clears `keys` and the
Bilibili login.

Scripts: `/presets/oca/` on the server lists ready-made ones (Bilibili play is
`scripts/bilibili-play.js`, copied to `server/presets/oca/`; run
`python server/presets.py sync` after editing it). On the phone, Settings →
云端资源 refreshes that list and installs a preset into `active.js`. With remote
control on, agents can still push any script with `POST /api/invoke` and a `js`
tool. Do not commit tokens.

## Harness on the phone

A floating ball (system overlay) expands into the agent chat. Ordinary talk is answered
in the chat. The agent only writes and installs a script when you explicitly ask for a
screen. The agent is bundled `pi-agent-core` + `pi-ai` running in its own V8 isolate
(`AgentRuntime`, `android/agent`). Settings (the gear) stores keys as pi `auth.json` and
the current model; built-in backends are DeepSeek, OpenAI, Anthropic, Google, OpenRouter,
Moonshot, ZAI, MiniMax, Groq, xAI, plus one custom OpenAI-compatible endpoint.

Hold 说 to talk: SenseVoice (sherpa-onnx) recognizes it on the phone (`LocalAsr`). Chat can take the mic from a script. The
model is not in the APK; it is read from `files/asr/sv/` (`model.int8.onnx`, `tokens.txt`).
For now copy it there with `adb push` to `/data/local/tmp` and
`run-as app.onlyclaws.android cp`. The sherpa-onnx AAR is downloaded into `app/libs/` on
the first Gradle run. Rebuild the JS bundle with `node android/agent/build.mjs`.
It asks `deepseek-flash` at `api.deepseek.com` with the key in `keys/deepseek`; paste a
`sk-…` key into the strip once to store it. The reply is compiled with V8, installed,
and watched for 1.5 s. A compile error, a failed `onStart`, or an early runtime error goes
back to the model; after three tries the previous script is put back. When the running
script is one the harness wrote, the next sentence edits it instead of starting over.

Scripts the harness writes start with `// oca:generated`. `OcApp.load` gives them
`overlay` (`gfx`, `ui`, `onFrame`, `onPointer`), `screen`, `tts`, `asr`, `llm`, `http`,
`socket`, `ssh`, `wallpaper`, and `oca` — not `keys`, `web`, or `desk` — on every load, including after
a restart. Scripts from the console keep every plugin. `llm.chat` uses the same
AgentStore key the agent uses; the script never sees the key.

A click on `data-action` calls `onAction` with `e.context` filled from `data-field` inputs.

## JS surface (host objects)

| Object | Role |
|--------|------|
| `oca.log` | log line |
| `screen` | Main UI inside the app. `show(html)` / `clear()`. Inline HTML and SVG only. `data-action` clicks call `onAction`. No navigation and no network loads. Separate from `web`. |
| `web` | `load` / `float` / `url` / `eval` / `touch` / `clear` / `loggedIn` / `showing`. `load` is in-app HTML. `float` puts a transparent WebView on the system overlay (HTML or http(s)); it is not muted; `touch(true)` takes input, default is pass-through. A login URL is shown in the app and closes once `SESSDATA` is set. Any other `url` is loaded off-screen, muted, and does not take touches. |
| `desk` | three screens: 运行, 配置, 日志. `desk.show({ title, status, login, running, keyReady, error, checking, open, tokens, gap, gapMin, gapMax, gapStep, prompts, prompt, custom, rows, stats, events })`. `tokens` is the running total. `open` is `运行` / `配置` / `日志` when the script wants to change screen. 开始 calls `start` after the script checks the saved key against the model. A failed check sets `error`. The gap slider reports `gap`. A preset reports its id. Custom text reports `promptText`. |
| `keys` | `get` / `set` / `has` for one private file per name, such as `deepseek`. The value is not drawn on the screen. |
| `gfx` | System overlay: `clear` / `rect` / `line` / `circle` / `text` / `text_width`. ARGB; 6-digit is opaque. `clear(0)` empties the window. A full-screen wash does not take touches, so the launcher can still change pages. Needs overlay permission. |
| `asr` | Same on-device SenseVoice as the chat ball: `warm` / `start` / `stop`, getters `ready` / `hasModel` / `listening`. `onSpeech({ text, partial, error? })`. One mic: script and chat cannot listen together. |
| `llm` | `ready` / `provider` / `model`; `chat({ messages, system? })` → `{ text, error, provider, model }`. A user message may include `image` as base64. Host sends the key. OpenAI-compatible backends only. |
| `shot` | `take()` → `{ b64, mime, w, h, error }`. JPEG of the whole display, including icons and the foreground app. One system capture consent, then reuse until the user stops it. No accessibility service. |
| `tts` | `say` / `stop` + `onDone` |
| `wallpaper` | The word 壁纸 maps only here. `load({ color, text })`, `load({ scene: "crash" })`, `load({ scene: "castle" })` (the bundled Infinity Castle fall), `load({ html })`, or `load({ url })` (remote page as wallpaper: https, or http on localhost/LAN). Inline HTML and remote pages run behind the icons with JavaScript and WebGL. `OcaWallpaper.tiltX/Y` and `gyroX/Y/Z` are radians. `onWallpaper(dt)` is the flat path: `clear` / `rect` / `line` / `circle` / `tri` / `text`. No touches, no launcher swipes. |
| `ui` | `w`/`h`, `safe`, `keyboard` (dp) |
| `http` / `fetch` | `http.request({ url, method, headers, body, timeoutMs })` and `fetch(url, init)` → `{ ok, status, body, error, headers }`. `fetch` also has `text()` / `json()`. Sync, https only. |
| `socket` | Outbound TCP. `open({ host, port, timeoutMs })` → `{ id, error }`. `send(id, { text } or { b64 })`. `recv(id, { maxBytes, timeoutMs })` → `{ text, b64, n, eof, error }`. `close(id)`. No listen. |
| `ssh` | `exec({ host, port, user, password` or `privateKey, command, timeoutMs, fingerprint })` → `{ code, stdout, stderr, error, fingerprint }`. One command, then the connection closes. The first host key is remembered; a change is refused unless `fingerprint` pins the new one. |

`http.request` blocks the script thread until the response or the timeout. Only `https`.
Connect timeout is 20s. `timeoutMs` defaults to 60000 and is clamped to 1000..120000.
`status` is 0 when no HTTP status came back. `error` is empty when a status did.
Header names are lower case. A body or response larger than 2MB is refused or cut.
The script does its own retries.

Swiping the app out of recents finishes the activity. The foreground service keeps
the script. If the phone kills that process, an exact alarm starts the service
again one second later, and `files/active.js` loads on the new process.

Script hooks: `onStart`, `onStop`, optional `onFrame`, `onAction`, `onPointer`, `onSpeech`, `onDone`.
Hooks are found on the global object, so declare them with `function`; a top-level
`const onStart = …` is not seen.

## Script engine

V8 through Javet (`javet-v8-android`, arm64 only). Modern JS works; there are no
timers, and host functions are synchronous. Each load gets a fresh runtime with only
the host objects above, so scripts cannot reach Java. Pending promise callbacks run
before a hook returns. Script code that runs 5 s without returning or calling a host
function is terminated; time inside a host call, such as `http.request`, does not
count. A host function that fails throws a JS `Error` with its message.
The stripped V8 library is about 62 MB, stored uncompressed in the APK.

Unit tests run the same container on the desktop JVM through
`javet-v8-macos-arm64`, so they need an Apple Silicon Mac.
