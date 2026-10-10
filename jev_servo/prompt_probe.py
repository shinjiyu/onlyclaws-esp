#!/usr/bin/env python3
"""Probe which prompt shapes make JEV pick sensible search moves.

Stuck pose from console run: looking steeply down, no face.
Correct-ish: raise look_el (j1+/j2+/j3− at this q) and/or sweep j0; NOT all-stay.
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from jev_servo.fk import look_angles, look_jacobian, fk_camera, predict_delta_look
from jev_servo.jev_client import JevClient
from jev_servo.mech import CHOICES, CRITERIA, JOINTS
from jev_servo.state import build_state, joint_instructions

Q = [1.289, -1.2, -0.46, 1.081]
SCENE = "objects:none"
GOAL = "对准人：把尖端相机画面里的人放到画面中央"

# At this q: raise el ≈ j1+, j2+, j3−  (from J)
RAISE_EL = {
    "j0": set(),  # az only
    "j1": {"toward_pos_s", "toward_pos_l"},
    "j2": {"toward_pos_s", "toward_pos_l"},
    "j3": {"toward_neg_s", "toward_neg_l"},
}
SWEEP_AZ = {"toward_neg_s", "toward_pos_s", "toward_neg_l", "toward_pos_l"}


def _predict_block(qi: int) -> str:
    J = look_jacobian(Q)
    j = JOINTS[qi]
    lines = [f"PREDICT motor {j.name} (idx={qi}):"]
    for name, dq in [
        ("stay", 0.0),
        ("toward_neg_s", -j.delta_s),
        ("toward_pos_s", +j.delta_s),
        ("toward_neg_l", -j.delta_l),
        ("toward_pos_l", +j.delta_l),
    ]:
        daz, del_ = predict_delta_look(J, qi, dq)
        lines.append(f"  {name}: δq={dq:+.3f} → Δaz={daz:+.4f} Δel={del_:+.4f}")
    return "\n".join(lines)


def _geo_header() -> str:
    az, el, z, p = look_angles(fk_camera(Q))
    J = look_jacobian(Q)
    return (
        f"q={Q}\n"
        f"look_az={az:.4f} look_el={el:.4f}\n"
        f"z_hat=[{z[0]:.3f},{z[1]:.3f},{z[2]:.3f}] p_mm=[{p[0]:.1f},{p[1]:.1f},{p[2]:.1f}]\n"
        f"J_daz=[{J[0,0]:+.3f},{J[0,1]:+.3f},{J[0,2]:+.3f},{J[0,3]:+.3f}]\n"
        f"J_del=[{J[1,0]:+.3f},{J[1,1]:+.3f},{J[1,2]:+.3f},{J[1,3]:+.3f}]\n"
    )


def variant_current(joint: str) -> tuple[str, str]:
    state = build_state(goal=GOAL, scene=SCENE + "; empty@center-mid area=1.00", scene_age_ms=10, q=Q, hist=[])
    return state, joint_instructions(joint)


def variant_current_no_empty(joint: str) -> tuple[str, str]:
    state = build_state(goal=GOAL, scene=SCENE, scene_age_ms=10, q=Q, hist=[])
    return state, joint_instructions(joint)


def variant_compact(joint: str) -> tuple[str, str]:
    j = next(x for x in JOINTS if x.name == joint)
    state = (
        "TASK: search for a human face with tip camera. TARGET_STATUS=MISSING.\n"
        "Use numbers only.\n"
        + _geo_header()
        + _predict_block(j.index)
        + "\nRULE: do not stay; change look_az or look_el. Prefer raising look_el (now too low)."
    )
    inst = (
        f"Pick one choice for motor {joint} only. "
        "Prefer the PREDICT row that increases look_el if |Δel| is available; "
        "else sweep look_az. Never stay while MISSING."
    )
    return state, inst


def variant_explicit_raise(joint: str) -> tuple[str, str]:
    j = next(x for x in JOINTS if x.name == joint)
    state = (
        "TARGET_STATUS=MISSING. Camera look_el is too negative (pointing at floor).\n"
        + _geo_header()
        + _predict_block(j.index)
        + "\nOBJECTIVE: maximize Δel this tick for this motor if any choice has Δel>0; "
        "else maximize |Δaz|. stay is forbidden."
    )
    inst = f"Motor {joint} only. Choose the option with largest Δel among PREDICT; if all Δel≈0 choose largest |Δaz|."
    return state, inst


def variant_bearing_error(joint: str) -> tuple[str, str]:
    """Fake a desired look bearing above current — gives |err'| like tracking."""
    az, el, _, _ = look_angles(fk_camera(Q))
    want_az, want_el = az, el + 0.35  # want to look up ~20°
    err_az, err_el = want_az - az, want_el - el
    j = next(x for x in JOINTS if x.name == joint)
    J = look_jacobian(Q)
    lines = [
        "TARGET_STATUS=MISSING but SEARCH_BEARING set (virtual).",
        f"current look_az={az:.4f} look_el={el:.4f}",
        f"want   look_az={want_az:.4f} look_el={want_el:.4f}",
        f"err_az={err_az:+.4f} err_el={err_el:+.4f}  (want err→0)",
        _predict_block(j.index),
        "For each choice, residual = hypot(err_az-Δaz, err_el-Δel). Pick min residual.",
    ]
    # precompute residuals into state so model doesn't mis-add
    for name, dq in [
        ("stay", 0.0),
        ("toward_neg_s", -j.delta_s),
        ("toward_pos_s", +j.delta_s),
        ("toward_neg_l", -j.delta_l),
        ("toward_pos_l", +j.delta_l),
    ]:
        daz, del_ = predict_delta_look(J, j.index, dq)
        r = (err_az - daz) ** 2 + (err_el - del_) ** 2
        lines.append(f"  residual[{name}]={r**0.5:.4f}")
    state = "\n".join(lines)
    inst = f"Motor {joint} only. Pick the choice with smallest residual[*]."
    return state, inst


def variant_one_question_raise(joint: str) -> tuple[str, str]:
    j = next(x for x in JOINTS if x.name == joint)
    az, el, z, _ = look_angles(fk_camera(Q))
    state = (
        f"look_el={el:.3f} (floor). z_z={z[2]:.3f}. MISSING face.\n"
        + _predict_block(j.index)
    )
    inst = (
        f"You only control {joint}. "
        "Which single choice most increases look_el (Δel most positive)? "
        "If this motor cannot change el, pick a non-zero Δaz sweep. Do not stay."
    )
    return state, inst


VARIANTS = [
    ("A_current+empty", variant_current),
    ("B_current_clean", variant_current_no_empty),
    ("C_compact_no_stay", variant_compact),
    ("D_explicit_max_Δel", variant_explicit_raise),
    ("E_virtual_bearing+residual", variant_bearing_error),
    ("F_one_liner_raise", variant_one_question_raise),
]


def score(joint: str, choice: str) -> str:
    if choice in ("stay", "widen_stay"):
        return "BAD_stay"
    if choice in RAISE_EL.get(joint, ()):
        return "GOOD_raise_el"
    if joint == "j0" and choice in SWEEP_AZ:
        return "OK_sweep_az"
    if choice in SWEEP_AZ:
        return "OK_move"
    return "OTHER"


def run_one(client: JevClient, tag: str, joint: str, state: str, inst: str) -> dict:
    t0 = time.perf_counter()
    try:
        r = client.choose(
            state=state,
            question_id=f"probe_{joint}",
            instructions=inst,
            criteria={k: CRITERIA[k] for k in CHOICES if k != "widen_stay"},  # drop widen for search
        )
        # restore full criteria keys expected — actually we removed widen; ok
        return {
            "tag": tag,
            "joint": joint,
            "choice": r["choice"],
            "score": score(joint, r["choice"]),
            "ms": r["latency_ms"],
            "conf": r.get("confidence"),
            "state_chars": len(state),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "tag": tag,
            "joint": joint,
            "choice": None,
            "score": "ERR",
            "ms": (time.perf_counter() - t0) * 1000,
            "conf": None,
            "state_chars": len(state),
            "error": str(exc)[:200],
        }


def main() -> int:
    client = JevClient()
    motors = ["j0", "j1", "j2", "j3"]
    jobs = []
    for tag, fn in VARIANTS:
        for joint in motors:
            state, inst = fn(joint)
            jobs.append((tag, joint, state, inst))

    print(f"probe {len(jobs)} calls at q={Q}", flush=True)
    rows = []
    # parallel but cap to avoid hammering
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {
            pool.submit(run_one, client, tag, joint, state, inst): (tag, joint)
            for tag, joint, state, inst in jobs
        }
        for fut in as_completed(futs):
            row = fut.result()
            rows.append(row)
            print(
                f"{row['tag']:28s} {row['joint']} → {row['choice']!s:16s} {row['score']:14s} "
                f"{row['ms']:.0f}ms chars={row['state_chars']}",
                flush=True,
            )

    rows.sort(key=lambda r: (r["tag"], r["joint"]))
    out = Path(__file__).resolve().parent / "runs" / "prompt_probe.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== summary by variant ===")
    for tag, _ in VARIANTS:
        subset = [r for r in rows if r["tag"] == tag]
        goods = sum(1 for r in subset if r["score"].startswith("GOOD"))
        oks = sum(1 for r in subset if r["score"].startswith("OK"))
        bads = sum(1 for r in subset if r["score"].startswith("BAD"))
        print(f"{tag:28s} GOOD_raise={goods} OK_move={oks} BAD_stay={bads}  "
              f"detail=" + ", ".join(f"{r['joint']}:{r['choice']}" for r in subset))

    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
