"""Mirror firmware capabilityAllowsTool — keep in sync with rlcd/src/capability.cpp.

`js` / `container` exist only on OnlyClaws Android (android/), not in ESP firmware.
"""

from __future__ import annotations


def tool_allowed_for_caps(tool: str, caps: list[str]) -> bool:
    name = (tool or "").strip()
    if not name:
        return False
    if name == "emit":
        return True
    if name in ("sensors.read", "sensors"):
        return "sensors" in caps
    if name in ("beep", "play_pcm"):
        return "audio" in caps
    if name == "say":
        return "tts" in caps
    if name in ("display", "gfx.clear", "gfx.flush"):
        return "panel" in caps
    if name == "arm" or name.startswith("arm."):
        return "arm" in caps
    if name == "js":
        return "container" in caps
    return False
