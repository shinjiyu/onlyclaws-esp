"""Tests for host-side choice sanitization with search phases."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from jev_servo.search import SearchSnapshot
from jev_servo.tick import sanitize_choice, synthesize


def test_raise_allows_j0_stay():
    q = [0.5, -1.0, 0.5, 1.5]
    snap = SearchSnapshot("raise", 0.5, 0.0, 0.0, 0.4, 1, 0, [])
    assert (
        sanitize_choice("j0", q[0], "stay", status="MISSING", hist=[], q_all=q, search=snap)
        == "stay"
    )


def test_sweep_forces_j0_motion():
    q = [0.3, 0.0, 1.5, 2.0]
    snap = SearchSnapshot("sweep", 1.0, 0.0, 0.5, 0.05, 1, 1, [0.0])
    ch = sanitize_choice("j0", q[0], "stay", status="MISSING", hist=[], q_all=q, search=snap)
    assert ch.startswith("toward_")


def test_synthesize_sweep_moves_j0():
    judged = {n: {"choice": "stay"} for n in ("j0", "j1", "j2", "j3")}
    q = [0.3, 0.0, 1.5, 2.0]
    snap = SearchSnapshot("sweep", 1.0, 0.0, 0.5, 0.05, 1, 1, [0.0])
    choices, _, _, need = synthesize(q, judged, hist=[], status="MISSING", search=snap)
    assert choices["j0"].startswith("toward_")
    assert need is True
