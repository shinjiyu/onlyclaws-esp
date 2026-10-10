"""Calibrated 4R tip-camera FK for Migi (RoArm-M2 topology).

Chain (base frame, mm, right-handed, +Z up):
  T = I
  T *= Rz(s0*q0) * Trans(0,0,L1)
  T *= Ry(s1*q1 + o_s) * Trans(L2A, 0, L2B)
  T *= Ry(s2*q2 + o_e) * Trans(L3A, 0, L3B)
  T *= Rot(wrist_axis * (s3*q3 + o_w)) * Trans(c) * Rot(cam_rotvec)

Parameters from model_migi.json (roarm_ident measure fit).
"""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

import numpy as np

_MODEL_PATH = Path(__file__).resolve().parent / "model_migi.json"


def _hat(w: np.ndarray) -> np.ndarray:
    x, y, z = w
    return np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]], dtype=float)


def _exp_so3(w: np.ndarray) -> np.ndarray:
    th = float(np.linalg.norm(w))
    if th < 1e-12:
        R = np.eye(3) + _hat(w)
    else:
        K = _hat(w / th)
        R = np.eye(3) + math.sin(th) * K + (1.0 - math.cos(th)) * (K @ K)
    U, _, Vt = np.linalg.svd(R)
    R2 = U @ Vt
    if np.linalg.det(R2) < 0:
        U = U.copy()
        U[:, -1] *= -1
        R2 = U @ Vt
    return R2


def _axis_ab(a: float, b: float) -> np.ndarray:
    sa, ca = math.sin(a), math.cos(a)
    v = np.array([ca, sa * math.cos(b), sa * math.sin(b)], dtype=float)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else np.array([1.0, 0.0, 0.0])


def _Rz(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=float)


def _Ry(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=float)


def _T_R(R: np.ndarray) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = R
    return T


def _T_t(t: Sequence[float]) -> np.ndarray:
    T = np.eye(4)
    T[:3, 3] = np.asarray(t, dtype=float)
    return T


@lru_cache(maxsize=1)
def load_model() -> dict[str, Any]:
    return json.loads(_MODEL_PATH.read_text(encoding="utf-8"))


def fk_camera(q: Sequence[float], *, model: dict[str, Any] | None = None) -> np.ndarray:
    """Return 4x4 T_base_camera at joint angles q (rad)."""
    m = model or load_model()
    x = np.asarray(m["theta"], dtype=float)
    sb, ss, se, sw = [int(s) for s in m["signs"]]
    qb = sb * float(q[0])
    qs = ss * float(q[1]) + float(x[5])
    qe = se * float(q[2]) + float(x[6])
    qw = sw * float(q[3]) + float(x[7])

    T = np.eye(4)
    T = T @ _T_R(_Rz(qb)) @ _T_t([0.0, 0.0, x[0]])
    T = T @ _T_R(_Ry(qs)) @ _T_t([x[1], 0.0, x[2]])
    T = T @ _T_R(_Ry(qe)) @ _T_t([x[3], 0.0, x[4]])
    T = T @ _T_R(_exp_so3(_axis_ab(float(x[8]), float(x[9])) * qw))
    T = T @ _T_t([x[10], x[11], x[12]])
    T = T @ _T_R(_exp_so3(x[13:16]))
    return T


def look_angles(T_cam: np.ndarray) -> tuple[float, float, np.ndarray, np.ndarray]:
    """Optical-axis spherical angles in base frame.

    Returns (az, el, z_hat, p_mm) where
      az = atan2(zy, zx), el = atan2(zz, hypot(zx,zy)),
      z_hat = camera +Z (look), p_mm = camera origin.
    """
    R = T_cam[:3, :3]
    p = T_cam[:3, 3]
    z = R[:, 2]
    n = float(np.linalg.norm(z))
    if n < 1e-12:
        z = np.array([1.0, 0.0, 0.0])
    else:
        z = z / n
    az = math.atan2(float(z[1]), float(z[0]))
    el = math.atan2(float(z[2]), math.hypot(float(z[0]), float(z[1])))
    return az, el, z, p


def look_jacobian(q: Sequence[float], *, eps: float = 1e-4) -> np.ndarray:
    """2x4 Jacobian: rows = (daz, del), cols = (j0..j3), rad/rad."""
    q0 = np.asarray(q, dtype=float)
    az0, el0, _, _ = look_angles(fk_camera(q0))
    J = np.zeros((2, 4), dtype=float)
    for i in range(4):
        dq = q0.copy()
        dq[i] += eps
        az1, el1, _, _ = look_angles(fk_camera(dq))
        # unwrap az finite difference
        daz = (az1 - az0 + math.pi) % (2 * math.pi) - math.pi
        J[0, i] = daz / eps
        J[1, i] = (el1 - el0) / eps
    return J


def predict_delta_look(J: np.ndarray, i: int, delta_q: float) -> tuple[float, float]:
    return float(J[0, i] * delta_q), float(J[1, i] * delta_q)


def predict_delta_uv(
    daz: float,
    del_: float,
    *,
    fov_h: float,
    fov_v: float,
) -> tuple[float, float]:
    """Pinhole bearing map: +Δaz of look → target moves −u; +Δel → target moves −v.

    Image coords: u right, v down, both in [0,1], center (0.5,0.5).
    """
    du = -daz / max(fov_h, 1e-6)
    dv = -del_ / max(fov_v, 1e-6)
    return du, dv


_FACE_RE = re.compile(
    r"(?:^|[;\s])face@(?P<u>0?\.\d+|1(?:\.0+)?)\s*,\s*(?P<v>0?\.\d+|1(?:\.0+)?)",
    re.I,
)


def parse_face_uv(scene: str) -> tuple[float, float] | None:
    m = _FACE_RE.search(scene or "")
    if not m:
        return None
    return float(m.group("u")), float(m.group("v"))


def format_model_snapshot(
    q: Sequence[float],
    *,
    scene: str = "",
    choice_deltas: dict[str, float] | None = None,
) -> str:
    """Numeric kinematics block for JEV state (no anthropomorphic language)."""
    m = load_model()
    T = fk_camera(q, model=m)
    az, el, z, p = look_angles(T)
    J = look_jacobian(q)
    fov_h = float(m["fov_h_rad"])
    fov_v = float(m["fov_v_rad"])
    sb, ss, se, sw = m["signs"]
    x = m["theta"]

    lines = [
        "GEOMETRIC MODEL (calibrated FK, numbers only — use this, do not invent limb metaphors):",
        f"  arm={m['name']} units=mm,rad frame={m['frame']}",
        "  T = Rz(s0 q0)·Tz(L1)·Ry(s1 q1+os)·T(L2A,0,L2B)·Ry(s2 q2+oe)·T(L3A,0,L3B)",
        "      ·R(a_w*(s3 q3+ow))·T(c)·R(rcam)",
        f"  signs=(s0,s1,s2,s3)=({sb},{ss},{se},{sw})",
        f"  L1={x[0]:.2f} L2A={x[1]:.2f} L2B={x[2]:.2f} L3A={x[3]:.2f} L3B={x[4]:.2f}",
        f"  offsets(os,oe,ow)=({x[5]:.4f},{x[6]:.4f},{x[7]:.4f})",
        f"  wrist_axis_ab=({x[8]:.4f},{x[9]:.4f}) c_mm=({x[10]:.2f},{x[11]:.2f},{x[12]:.2f})",
        f"  cam_rotvec=({x[13]:.4f},{x[14]:.4f},{x[15]:.4f})",
        "CAMERA_AT_Q:",
        f"  p_cam_mm=[{p[0]:.1f},{p[1]:.1f},{p[2]:.1f}]",
        f"  z_hat(look)=[{z[0]:.3f},{z[1]:.3f},{z[2]:.3f}]",
        f"  look_az={az:.4f} look_el={el:.4f}  (az=atan2(zy,zx), el=atan2(zz,hypot(zx,zy)))",
        "LOOK_JACOBIAN J (rows=daz,del; cols=j0,j1,j2,j3) [rad/rad]:",
        f"  daz/dq = [{J[0,0]:+.3f},{J[0,1]:+.3f},{J[0,2]:+.3f},{J[0,3]:+.3f}]",
        f"  del/dq = [{J[1,0]:+.3f},{J[1,1]:+.3f},{J[1,2]:+.3f},{J[1,3]:+.3f}]",
        f"  |J| col norms = [{np.linalg.norm(J[:,0]):.3f},{np.linalg.norm(J[:,1]):.3f},"
        f"{np.linalg.norm(J[:,2]):.3f},{np.linalg.norm(J[:,3]):.3f}]",
        "IMAGE map (u right, v down, center 0.5,0.5):",
        f"  Δu ≈ -Δaz/{fov_h:.2f};  Δv ≈ -Δel/{fov_v:.2f}",
        "  Choose δq so predicted (Δu,Δv) reduces image error when a target is visible;",
        "  when MISSING, change look_az/look_el to sweep unseen bearings (use J, not habit).",
    ]

    face = parse_face_uv(scene)
    if face is not None:
        u, v = face
        lines.append(
            f"TARGET_IMAGE: u={u:.3f} v={v:.3f}  err_u={u-0.5:+.3f} err_v={v-0.5:+.3f}"
        )
        lines.append(
            "  Goal: drive (err_u,err_v)→(0,0) via Δu≈-err_u, Δv≈-err_v this tick (small step)."
        )

    if choice_deltas:
        lines.append("CHOICE→Δlook / Δuv for THIS motor (apply J column · δ):")
        # choice_deltas is filled by caller per-joint in joint-specific block; here global optional
        for name, dq in choice_deltas.items():
            lines.append(f"  {name}: δq={dq:+.3f}")

    return "\n".join(lines)


def format_joint_predict(
    joint_index: int,
    q: Sequence[float],
    deltas: Sequence[tuple[str, float]],
    *,
    scene: str = "",
) -> str:
    """Per-motor predicted Δlook / Δuv for each discrete choice delta."""
    J = look_jacobian(q)
    m = load_model()
    fov_h = float(m["fov_h_rad"])
    fov_v = float(m["fov_v_rad"])
    face = parse_face_uv(scene)
    lines = [f"PREDICT for motor index {joint_index} (J col {joint_index}):"]
    for name, dq in deltas:
        daz, del_ = predict_delta_look(J, joint_index, dq)
        du, dv = predict_delta_uv(daz, del_, fov_h=fov_h, fov_v=fov_v)
        bit = (
            f"  {name}: δq={dq:+.3f} → Δaz={daz:+.4f} Δel={del_:+.4f} "
            f"→ Δu={du:+.4f} Δv={dv:+.4f}"
        )
        if face is not None:
            u, v = face
            nu, nv = (u - 0.5) + du, (v - 0.5) + dv
            bit += f" → |err'|={math.hypot(nu, nv):.4f}"
        lines.append(bit)
    return "\n".join(lines)
