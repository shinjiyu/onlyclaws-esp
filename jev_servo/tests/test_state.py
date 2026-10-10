"""Tests for goal vs scene + compact geometry-driven state."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from jev_servo.state import (
    best_missing_choice,
    build_state,
    goal_is_person,
    infer_sought_kinds,
    joint_instructions,
    scene_for_jev,
    target_status,
)


def test_infer_person_goal():
    assert "face" in infer_sought_kinds("对准人：把尖端相机画面里的人放到画面中央")
    assert goal_is_person("对准人")


def test_missing_when_no_person():
    scene = "tv@0.33,0.27 span=0.65 left-upper; chair@0.75,0.85 right-lower"
    assert target_status("对准人", scene) == "MISSING"


def test_centered_person():
    scene = "face@0.50,0.45 span=0.2 center-mid s=0.8"
    assert target_status("对准人 / center the person", scene) == "CENTERED"


def test_visible_not_centered():
    scene = "face@0.20,0.40 span=0.2 left-mid s=0.7"
    assert target_status("aim at person", scene) == "VISIBLE"


def test_coco_person_ignored_for_person_goal():
    scene = "person@0.50,0.50 span=0.99 center-mid s=0.66; tie@0.12,0.22"
    assert target_status("对准人", scene) == "MISSING"


def test_scene_strips_empty():
    assert "empty@" not in scene_for_jev("objects:none; empty@center-mid area=1.00")


def test_compact_missing_state():
    from jev_servo.search import SearchSnapshot

    snap = SearchSnapshot("raise", 1.289, -0.2, 0.0, 0.98, 1, 0, [])
    text = build_state(
        goal="对准人",
        scene="objects:none; empty@center-mid area=1.00",
        scene_age_ms=10,
        q=[1.289, -1.2, -0.46, 1.081],
        hist=[],
        search=snap,
    )
    assert "TARGET_STATUS=MISSING" in text
    assert "SEARCH_PLAN" in text
    assert "phase=raise" in text
    assert "PREDICT j0" in text
    assert "BEST=" in text
    assert "empty@" not in text
    assert "GEOMETRIC MODEL" not in text
    assert len(text) < 4000


def test_best_missing_raises_el_on_j2():
    from jev_servo.search import SearchSnapshot

    q = [1.289, -1.2, -0.46, 1.081]
    snap = SearchSnapshot("raise", 1.289, -0.2, 0.0, 0.98, 1, 0, [])
    ch = best_missing_choice("j2", q, snap)
    assert "pos" in ch


def test_motor_instructions_best():
    inst = joint_instructions("j1")
    assert "BEST" in inst
    assert "SEARCH" in inst
