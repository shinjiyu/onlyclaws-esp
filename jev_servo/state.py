"""Pack shared JEV state text (no raw images).

Prompt shape follows prompt_probe: short look + PREDICT tables + explicit
objective. SearchPlanner supplies advancing want_az/want_el (room sweep).
"""

from __future__ import annotations

import math
import re
from typing import Any, Sequence

import numpy as np

from .fk import (
    fk_camera,
    look_angles,
    look_jacobian,
    parse_face_uv,
    predict_delta_look,
    predict_delta_uv,
    load_model,
)
from .mech import JOINTS
from .search import SearchSnapshot


_TARGET_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("face", ("person", "face", "人", "人类", "对准人", "人脸", "脸")),
    ("laptop", ("laptop", "笔记本", "电脑")),
    ("tv", ("tv", "monitor", "显示器", "电视", "屏幕")),
    ("cup", ("cup", "杯子")),
    ("bottle", ("bottle", "瓶子")),
    ("chair", ("chair", "椅子")),
)


def goal_is_person(goal: str) -> bool:
    return "face" in infer_sought_kinds(goal)


def infer_sought_kinds(goal: str) -> list[str]:
    g = goal.lower()
    found: list[str] = []
    for kind, aliases in _TARGET_ALIASES:
        if any(a.lower() in g for a in aliases):
            if kind not in found:
                found.append(kind)
    return found


def scene_has_kind(scene: str, kind: str) -> bool:
    s = (scene or "").lower()
    if re.search(rf"(?:^|[;\s]){re.escape(kind)}@", s):
        return True
    return False


def target_status(goal: str, scene: str) -> str:
    kinds = infer_sought_kinds(goal)
    if not kinds:
        return "UNSPECIFIED"
    present = [k for k in kinds if scene_has_kind(scene, k)]
    if not present:
        return "MISSING"
    for k in present:
        m = re.search(rf"(?:^|[;\s]){re.escape(k)}@([^;]+)", scene, re.I)
        if m and "center-" in m.group(1).lower():
            return "CENTERED"
    return "VISIBLE"


def scene_for_jev(scene: str) -> str:
    parts = [p.strip() for p in (scene or "").split(";") if p.strip()]
    kept = [p for p in parts if not p.lower().startswith("empty@")]
    return "; ".join(kept) if kept else "objects:none"


def format_q_line(q: Sequence[float]) -> str:
    parts = []
    for j, v in zip(JOINTS, q):
        room_lo = v - j.qmin
        room_hi = j.qmax - v
        parts.append(
            f"{j.name}={v:.3f} lim=[{j.qmin:.2f},{j.qmax:.2f}] "
            f"room_neg={room_lo:.2f} room_pos={room_hi:.2f}"
        )
    return "; ".join(parts)


def choice_streaks(hist: Sequence[dict[str, Any]]) -> dict[str, tuple[str, int]]:
    out: dict[str, tuple[str, int]] = {}
    if not hist:
        return out
    last = hist[-1].get("choices") or {}
    for name, ch in last.items():
        n = 0
        for h in reversed(hist):
            c = (h.get("choices") or {}).get(name)
            if c != ch:
                break
            n += 1
        out[name] = (str(ch), n)
    return out


def format_hist(hist: Sequence[dict[str, Any]], *, max_ticks: int = 4) -> str:
    if not hist:
        return "(empty)"
    lines = []
    streaks = choice_streaks(hist)
    if streaks:
        bits = [f"{n}:{ch}×{k}" for n, (ch, k) in streaks.items() if k >= 2]
        if bits:
            lines.append("streaks: " + ", ".join(bits))
    for h in list(hist)[-max_ticks:]:
        sp = h.get("search") or {}
        lines.append(
            f"t={h.get('t')} phase={sp.get('phase','?')} "
            f"want_az={sp.get('want_az')} ch={h.get('choices')} "
            f"q*={[round(x, 3) for x in (h.get('q_star') or [])]}"
        )
    return "\n".join(lines)


def format_compact_look(q: Sequence[float], scene: str) -> str:
    m = load_model()
    az, el, z, p = look_angles(fk_camera(q, model=m))
    J = look_jacobian(q)
    fov_h = float(m["fov_h_rad"])
    fov_v = float(m["fov_v_rad"])
    lines = [
        "LOOK (calibrated FK → numbers only):",
        f"  look_az={az:.4f} look_el={el:.4f}",
        f"  z_hat=[{z[0]:.3f},{z[1]:.3f},{z[2]:.3f}] p_mm=[{p[0]:.1f},{p[1]:.1f},{p[2]:.1f}]",
        f"  J_daz/dq=[{J[0,0]:+.3f},{J[0,1]:+.3f},{J[0,2]:+.3f},{J[0,3]:+.3f}]",
        f"  J_del/dq=[{J[1,0]:+.3f},{J[1,1]:+.3f},{J[1,2]:+.3f},{J[1,3]:+.3f}]",
        f"  |J|cols=[{float(np.linalg.norm(J[:,0])):.2f},"
        f"{float(np.linalg.norm(J[:,1])):.2f},"
        f"{float(np.linalg.norm(J[:,2])):.2f},"
        f"{float(np.linalg.norm(J[:,3])):.2f}]",
        f"  image: Δu≈-Δaz/{fov_h:.2f}  Δv≈-Δel/{fov_v:.2f}  (u right, v down, center 0.5)",
    ]
    face = parse_face_uv(scene)
    if face is not None:
        u, v = face
        lines.append(
            f"TARGET_IMAGE u={u:.3f} v={v:.3f} err_u={u-0.5:+.3f} err_v={v-0.5:+.3f}"
        )
    return "\n".join(lines)


def format_choice_predicts(
    q: Sequence[float],
    scene: str,
    status: str,
    search: SearchSnapshot | None,
) -> str:
    m = load_model()
    fov_h = float(m["fov_h_rad"])
    fov_v = float(m["fov_v_rad"])
    J = look_jacobian(q)
    face = parse_face_uv(scene)
    phase = search.phase if search else "idle"
    err_az = float(search.err_az) if search and status == "MISSING" else 0.0
    err_el = float(search.err_el) if search and status == "MISSING" else 0.0

    blocks = []
    for j in JOINTS:
        lines = [f"PREDICT {j.name} (idx={j.index}):"]
        best_name = "stay"
        best_score = float("inf")
        for name, dq in [
            ("stay", 0.0),
            ("toward_neg_s", -j.delta_s),
            ("toward_pos_s", +j.delta_s),
            ("toward_neg_l", -j.delta_l),
            ("toward_pos_l", +j.delta_l),
        ]:
            qn = float(q[j.index]) + dq
            if qn < j.qmin - 1e-6 or qn > j.qmax + 1e-6:
                lines.append(f"  {name}: INVALID (limit)")
                continue
            daz, del_ = predict_delta_look(J, j.index, dq)
            du, dv = predict_delta_uv(daz, del_, fov_h=fov_h, fov_v=fov_v)
            if face is not None:
                u, v = face
                score = math.hypot((u - 0.5) + du, (v - 0.5) + dv)
                metric = f"|err'|={score:.4f}"
            elif status == "MISSING" and search is not None:
                score = math.hypot(err_az - daz, err_el - del_)
                # raise: j0 may stay; sweep: forbidding stay on search DOF
                if name in ("stay", "widen_stay"):
                    if phase == "raise" and j.name == "j0":
                        pass  # stay allowed / competitive
                    elif phase == "sweep" and j.name in ("j1", "j2", "j3") and abs(err_el) < 0.2:
                        pass  # pitch links may hold while yaw sweeps
                    else:
                        score += 10.0
                metric = f"residual={score:.4f}"
            else:
                score = -(abs(daz) + abs(del_))
                metric = f"|Δlook|={-score:.4f}"
            lines.append(
                f"  {name}: δq={dq:+.3f} Δaz={daz:+.4f} Δel={del_:+.4f} "
                f"Δu={du:+.4f} Δv={dv:+.4f} {metric}"
            )
            if score < best_score:
                best_score = score
                best_name = name
        lines.append(f"  BEST={best_name}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def build_state(
    *,
    goal: str,
    scene: str,
    scene_age_ms: float,
    q: Sequence[float],
    hist: Sequence[dict[str, Any]],
    search: SearchSnapshot | None = None,
) -> str:
    sought = infer_sought_kinds(goal)
    status = target_status(goal, scene)
    scene_j = scene_for_jev(scene)

    if status == "MISSING":
        phase = search.phase if search else "raise"
        if phase == "raise":
            objective = (
                "OBJECTIVE: SEARCH phase=raise. Drive err_el→0 (PREDICT residual). "
                "j0: prefer stay. j1/j2/j3: move. stay forbidden on pitch motors."
            )
        else:
            objective = (
                "OBJECTIVE: SEARCH phase=sweep. Drive err_az→0 with j0 "
                "(one direction toward want_az — do NOT dither). "
                "Pitch motors: stay if |err_el| small. stay forbidden on j0."
            )
    elif status == "CENTERED":
        objective = "OBJECTIVE: TARGET_STATUS=CENTERED. Prefer stay/widen_stay."
    elif status == "VISIBLE":
        objective = (
            "OBJECTIVE: TARGET_STATUS=VISIBLE. "
            "Pick PREDICT row with smallest |err'| (face → image center)."
        )
    else:
        objective = "OBJECTIVE: advance GOAL using PREDICT for THIS motor."

    search_block = ""
    if status == "MISSING" and search is not None:
        from .search import SearchPlanner

        search_block = SearchPlanner().format_block(search) + "\n"

    return (
        f"GOAL: {goal.strip()}\n"
        f"TARGET_STATUS={status} sought={sought or ['?']}\n"
        f"SCENE(age_ms={scene_age_ms:.0f}): {scene_j}\n"
        f"{objective}\n"
        f"{search_block}"
        f"{format_compact_look(q, scene_j)}\n"
        f"{format_choice_predicts(q, scene_j, status, search)}\n"
        f"Q: {format_q_line(q)}\n"
        f"HIST:\n{format_hist(hist)}\n"
    )


def joint_instructions(joint_name: str) -> str:
    j = next(x for x in JOINTS if x.name == joint_name)
    return (
        f"Motor '{j.name}' only (idx={j.index}). "
        f"Read PREDICT {j.name} and pick its BEST choice. "
        "Follow SEARCH phase rules in OBJECTIVE. "
        "Do not narrate other motors."
    )


def best_missing_choice(
    joint_name: str,
    q: Sequence[float],
    search: SearchSnapshot | None = None,
) -> str:
    """Host backstop matching PREDICT residual against SEARCH_BEARING."""
    j = next(x for x in JOINTS if x.name == joint_name)
    az, el, _, _ = look_angles(fk_camera(q))
    J = look_jacobian(q)
    if search is not None:
        err_az, err_el = search.err_az, search.err_el
        phase = search.phase
    else:
        err_az, err_el = 0.0, max(-0.2, el + 0.35) - el
        phase = "raise"

    if phase == "raise" and joint_name == "j0":
        return "stay"
    if phase == "sweep" and joint_name in ("j1", "j2", "j3") and abs(err_el) < 0.2:
        return "stay"

    best_name = "toward_pos_s"
    best_score = float("inf")
    for name, dq in [
        ("toward_neg_s", -j.delta_s),
        ("toward_pos_s", +j.delta_s),
        ("toward_neg_l", -j.delta_l),
        ("toward_pos_l", +j.delta_l),
    ]:
        qn = float(q[j.index]) + dq
        if qn < j.qmin - 1e-6 or qn > j.qmax + 1e-6:
            continue
        daz, del_ = predict_delta_look(J, j.index, dq)
        score = math.hypot(err_az - daz, err_el - del_)
        if score < best_score:
            best_score = score
            best_name = name
    return best_name
