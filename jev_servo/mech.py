"""Migi / RoArm-M2 motor table for JEV interval mapping.

Names are kinematic motors (j0..j3). Geometry lives in fk.py + model_migi.json.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JointSpec:
    name: str
    index: int
    role: str
    qmin: float
    qmax: float
    delta_s: float  # small step (rad)
    delta_l: float  # large step (rad)
    eps: float  # stay half-width
    w: float  # directed interval half-width
    dmax: float  # max |mid - q| per tick
    widen_eps: float


# Soft software limits (aligned with firmware: base ±π, shoulder ±π/2).
JOINTS: tuple[JointSpec, ...] = (
    # δl≈0.55 ≈ tip-cam HFOV chunk with ~40% overlap (faster traverse).
    JointSpec("j0", 0, "q0_base_yaw", -3.05, 3.05, 0.18, 0.55, 0.05, 0.08, 0.60, 0.12),
    JointSpec("j1", 1, "q1_link1_pitch", -1.2, 1.2, 0.08, 0.20, 0.04, 0.06, 0.30, 0.10),
    JointSpec("j2", 2, "q2_link2_pitch", -0.7, 2.5, 0.10, 0.25, 0.05, 0.07, 0.35, 0.12),
    JointSpec("j3", 3, "q3_tip_pitch", 1.0, 5.2, 0.10, 0.28, 0.05, 0.07, 0.35, 0.12),
)

JOINT_BY_NAME = {j.name: j for j in JOINTS}

KINEMATICS_TEXT = """\
STRUCTURE (see GEOMETRIC MODEL block for calibrated numbers + Jacobian):
  4R serial: q0 yaw about +Z → q1,q2 pitch about link +Y → q3 about tip axis → tip camera
  Camera pose T_base_cam(q) and look direction z_hat = R_cam[:,2] are computed each tick.
  Choices change qi by ±δs/±δl; effects on look/image are the PREDICT tables (J·δq).
"""

CHOICES = (
    "stay",
    "toward_neg_s",
    "toward_pos_s",
    "toward_neg_l",
    "toward_pos_l",
    "widen_stay",
)

CRITERIA = {
    "stay": "δq=0. Only if TARGET_STATUS=CENTERED or PREDICT BEST=stay. Forbidden when MISSING.",
    "toward_neg_s": "δq=−δs. Use when PREDICT marks this BEST (or smallest residual/|err'|).",
    "toward_pos_s": "δq=+δs. Use when PREDICT marks this BEST (or smallest residual/|err'|).",
    "toward_neg_l": "δq=−δl. Larger step when PREDICT BEST needs it and room allows.",
    "toward_pos_l": "δq=+δl. Larger step when PREDICT BEST needs it and room allows.",
    "widen_stay": "Wide hold. Only when TARGET_STATUS=CENTERED.",
}
