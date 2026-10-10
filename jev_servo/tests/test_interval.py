"""Unit tests for choice → safe interval mapping."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from jev_servo.interval import choice_to_interval, waypoint_from_interval
from jev_servo.mech import JOINT_BY_NAME
from jev_servo.tick import synthesize


def test_stay_contains_q():
    j = JOINT_BY_NAME["j0"]
    q = 0.2
    iv = choice_to_interval("stay", q, j)
    assert iv.contains(q)
    assert iv.width >= j.eps * 2 - 1e-9
    assert waypoint_from_interval(iv, q) == q


def test_pos_step_moves_midpoint():
    j = JOINT_BY_NAME["j0"]
    q = 0.0
    iv = choice_to_interval("toward_pos_s", q, j)
    assert iv.mid > q
    assert abs(iv.mid - q) <= j.dmax + 1e-9
    assert j.qmin <= iv.lo <= iv.hi <= j.qmax
    wp = waypoint_from_interval(iv, q)
    assert wp == iv.mid


def test_limit_clip_and_dmax():
    j = JOINT_BY_NAME["j0"]
    q = j.qmax - 0.01
    iv = choice_to_interval("toward_pos_l", q, j)
    assert iv.hi <= j.qmax + 1e-9
    assert abs(iv.mid - q) <= j.dmax + 1e-6


def test_toward_pos_near_max_still_advances():
    """Regression: δl past qmax must not collapse to a stay interval (traverse freeze)."""
    j = JOINT_BY_NAME["j0"]
    q = 2.669  # live stall pose
    iv = choice_to_interval("toward_pos_l", q, j)
    wp = waypoint_from_interval(iv, q)
    assert wp > q + 1e-3
    assert wp <= j.qmax + 1e-9


def test_invalid_choice_falls_back_stay():
    j = JOINT_BY_NAME["j2"]
    q = 2.0
    iv = choice_to_interval("not_a_choice", q, j)
    assert iv.contains(q)


def test_synthesize_hold_when_in_range():
    q = [-0.09, 0.35, 2.15, 3.90]
    judged = {
        "j0": {"choice": "stay"},
        "j1": {"choice": "stay"},
        "j2": {"choice": "stay"},
        "j3": {"choice": "stay"},
    }
    choices, intervals, q_star, need_move = synthesize(q, judged)
    assert choices["j0"] == "stay"
    assert need_move is False
    assert q_star == list(q)
    assert all(intervals[n].contains(q[i]) for i, n in enumerate(choices))
