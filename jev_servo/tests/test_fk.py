"""Tests for calibrated FK helpers."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from jev_servo.fk import fk_camera, look_angles, look_jacobian
from jev_servo.state import build_state


def test_fk_camera_shape():
    T = fk_camera([0.0, 0.0, 1.57, 3.14])
    assert T.shape == (4, 4)
    assert abs(np.linalg.det(T[:3, :3]) - 1.0) < 1e-5


def test_look_jacobian_finite():
    J = look_jacobian([0.1, -0.2, 1.5, 2.5])
    assert J.shape == (2, 4)
    assert np.all(np.isfinite(J))
    assert float(np.max(np.linalg.norm(J, axis=0))) > 0.1


def test_compact_state_has_look_not_long_fk():
    text = build_state(
        goal="对准人",
        scene="face@0.20,0.40 left-mid",
        scene_age_ms=5,
        q=[-0.1, 0.2, 1.8, 2.5],
        hist=[],
    )
    assert "LOOK" in text
    assert "PREDICT" in text
    assert "TARGET_IMAGE" in text
    assert "look UP" not in text
    assert "L1=" not in text  # no long length dump


def test_optical_axis_unit():
    _, _, z, _ = look_angles(fk_camera([0.2, 0.1, 1.6, 2.8]))
    assert abs(math.sqrt(float(z @ z)) - 1.0) < 1e-6
