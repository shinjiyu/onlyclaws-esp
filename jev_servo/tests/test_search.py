"""Tests for room-search planner (advancing want_az)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from jev_servo.search import SearchPlanner
from jev_servo.state import build_state, best_missing_choice


def test_raise_then_sweep_advances_az():
    p = SearchPlanner(step_az=0.5, el_tol=0.14, az_tol=0.18)
    # Start looking at floor
    s1 = p.update(look_az=0.0, look_el=-1.0, status="MISSING")
    assert s1.phase == "raise"
    assert abs(s1.err_az) < 1e-6  # yaw held during raise
    assert s1.err_el > 0

    # Elevated enough → sweep with nonzero want_az offset
    s2 = p.update(look_az=0.0, look_el=s1.want_el, status="MISSING")
    assert s2.phase == "sweep"
    assert abs(s2.err_az) > 0.2  # demand yaw motion

    # Reach waypoint → next waypoint further along
    s3 = p.update(look_az=s2.want_az, look_el=s2.want_el, status="MISSING")
    assert s3.phase == "sweep"
    assert s3.visited_n >= 1
    assert abs(s3.want_az - s2.want_az) > 0.3


def test_state_includes_search_plan():
    from jev_servo.search import SearchSnapshot

    snap = SearchSnapshot(
        phase="sweep",
        want_az=1.0,
        want_el=0.0,
        err_az=0.5,
        err_el=0.1,
        sweep_dir=1,
        visited_n=2,
        visited_az=[0.0, 0.5],
    )
    text = build_state(
        goal="对准人",
        scene="objects:none",
        scene_age_ms=1,
        q=[0.2, 0.0, 1.5, 2.0],
        hist=[],
        search=snap,
    )
    assert "SEARCH_PLAN phase=sweep" in text
    assert "err_az=" in text
    assert "want_az=1.0000" in text


def test_best_j0_stay_during_raise():
    from jev_servo.search import SearchSnapshot

    snap = SearchSnapshot("raise", 0.0, 0.0, 0.0, 0.5, 1, 0, [])
    assert best_missing_choice("j0", [0.0, -1.0, 0.5, 1.5], snap) == "stay"


def test_best_j0_moves_during_sweep():
    from jev_servo.search import SearchSnapshot

    # err_az positive → need +daz; j0 toward_neg gives +daz at typical pose (J[0,0]=-1)
    snap = SearchSnapshot("sweep", 1.0, 0.0, 0.5, 0.05, 1, 1, [0.0])
    ch = best_missing_choice("j0", [0.3, 0.0, 1.5, 2.0], snap)
    assert ch.startswith("toward_")
