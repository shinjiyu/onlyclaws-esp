# ADR 0010 — OCA downloads resources without a remote-control wire

## Context

OCA already packages identity (`session.json`, ADR 0009) and can receive `js` invokes over the same device session WebSocket the boards use (`SessionWire`). That long-lived connection is useful for console push, but it is the wrong default for a phone that mostly runs a local agent and occasional preset scripts. OnlyClaws is shifting to treat OCA as a first-class client that **pulls** catalog resources from the public HTTPS API instead of staying online for remote control.

## Decision

1. **Download-only is the default host mode.** `OcPrefs.remoteControl` defaults to false. `OcService` still runs (chat ball, wallpaper, local agent) but does **not** open `SessionWire`.
2. **Presets install over HTTPS.** The phone lists `GET /api/presets?kind=oca` and fetches `GET /api/presets/{id}/source` (already public), then writes `files/active.js` and loads it — no device token, no WebSocket.
3. **Remote control is opt-in.** Turning on「接受远控」in settings starts the existing session wire so console deploy / agent `invoke` keep working for development and fleets that need push.
4. **Identity stays optional for download-only.** Packaged `session.json` is still required for remote control and for install packages; a phone with no token can still pull and run public OCA presets.

## Consequences

- Phones no longer show as connected on the console unless remote control is enabled.
- `POST /api/presets/{id}/deploy` only reaches phones that opted into the wire.
- Cloud catalog and on-device install UI must stay aligned with `server/presets.py` (run `python server/presets.py sync` after editing origins).
