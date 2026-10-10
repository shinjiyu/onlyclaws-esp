"""Unit tests for invoke capability filter (no FastAPI / DB required)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from capability_policy import tool_allowed_for_caps


def test_emit_always():
    assert tool_allowed_for_caps("emit", [])
    assert tool_allowed_for_caps("emit", ["arm"])


def test_panel_tools():
    caps = ["core", "panel", "audio"]
    assert tool_allowed_for_caps("gfx.flush", caps)
    assert tool_allowed_for_caps("beep", caps)
    assert not tool_allowed_for_caps("arm.stream", caps)


def test_roarm_tools():
    caps = ["core", "arm"]
    assert tool_allowed_for_caps("arm.stream", caps)
    assert tool_allowed_for_caps("arm.feedback", caps)
    assert tool_allowed_for_caps("arm.stop", caps)
    assert not tool_allowed_for_caps("gfx.flush", caps)
    assert not tool_allowed_for_caps("beep", caps)
    assert not tool_allowed_for_caps("sensors.read", caps)


def test_unknown_denied():
    assert not tool_allowed_for_caps("shell.exec", ["core", "arm", "panel"])
    assert not tool_allowed_for_caps("", ["arm"])


if __name__ == "__main__":
    test_emit_always()
    test_panel_tools()
    test_roarm_tools()
    test_unknown_denied()
    print("ok")
