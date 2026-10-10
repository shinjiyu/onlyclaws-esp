"""Presence mission: Traverse (joint-space sweep) ↔ Follow (image UV).

No FK / look_az as authority. j0 steps are in joint radians; follow uses tip
image error only (Δu≈−Δaz heuristic encoded as fixed joint signs).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from typing import Any, Sequence

import numpy as np

from .fk import fk_camera, look_angles
from .interval import choice_to_interval, waypoint_from_interval
from .mech import JOINTS, JOINT_BY_NAME
from .presence import Presence


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _toward(joint_name: str, q: float, target: float, *, tol: float) -> str:
    j = JOINT_BY_NAME[joint_name]
    err = target - q
    if abs(err) <= tol:
        return "stay"
    step = j.delta_l if abs(err) > j.delta_l * 1.2 else j.delta_s
    if err > 0:
        return "toward_pos_l" if step >= j.delta_l else "toward_pos_s"
    return "toward_neg_l" if step >= j.delta_l else "toward_neg_s"


@dataclass
class TraversePlanner:
    """Full-base yaw (~±π) at several pitch rows (high → mid).

    Entering search: *stow* (pull tip in toward base Z + yaw to mid-axis) →
    *raise* (look-up search row) → *sweep*. Stow is a visibly shorter reach
    (~55mm radial vs ~150mm at raise) so the room scan is not started from a
    stuck follow pose with the tip still out.
    """

    phase: str = "stow"  # stow | raise | seek_start | sweep
    sweep_dir: int = 1
    visited_j0: list[float] = field(default_factory=list)
    elbow_q: float = 2.40
    elbow_min_safe: float = 2.20
    # (shoulder q1, wrist q3). FK look_el: higher q3 actually tilts tip DOWN.
    # Rows ordered high-el → lower-el for person search (do not start at "desk dive").
    el_rows: tuple[tuple[float, float], ...] = (
        (0.30, 3.80),  # look up   el≈+25°
        (0.18, 4.15),  # mid       el≈−3°  (two FOV-tall bands cover standing person)
    )
    # Start looking up so standing faces are not stuck at top of frame.
    el_row: int = 0
    raise_tol: float = 0.18
    # ≈ tip HFOV·0.55 — one large yaw tick ≈ one camera view with overlap.
    step_j0: float = 0.55
    j0_margin: float = 0.08
    el_advance_every: int = 8
    # Compact "on-axis" tuck (FK: r_xy≈55mm). Distinct from raise so stow moves.
    stow_j0: float = 0.0
    stow_q1: float = -0.25
    stow_q2: float = 2.45
    stow_q3: float = 3.55
    stow_tol: float = 0.10
    stow_j0_tol: float = 0.18
    _seek_done: bool = False
    _row_samples: int = 0

    @property
    def raise_q1(self) -> float:
        return self.el_rows[min(self.el_row, len(self.el_rows) - 1)][0]

    @property
    def raise_q2(self) -> float:
        return max(self.elbow_q, self.elbow_min_safe)

    @property
    def raise_q3(self) -> float:
        return self.el_rows[min(self.el_row, len(self.el_rows) - 1)][1]

    def reset(self) -> None:
        self.begin_global_search()

    def begin_global_search(self) -> None:
        """Pull tip in + mid-axis, then raise look-up, then sweep."""
        self.phase = "stow"
        self.sweep_dir = 1
        self.visited_j0 = []
        self._seek_done = False
        self.el_row = 0
        self._row_samples = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "sweep_dir": self.sweep_dir,
            "visited_n": len(self.visited_j0),
            "visited_j0": [round(x, 3) for x in self.visited_j0[-16:]],
            "el_row": self.el_row,
            "el_rows_n": len(self.el_rows),
            "row_samples": self._row_samples,
            "raise_q": [self.raise_q1, self.raise_q2, self.raise_q3],
            "stow_q": [self.stow_j0, self.stow_q1, self.stow_q2, self.stow_q3],
            "j0_span": [
                round(JOINT_BY_NAME["j0"].qmin + self.j0_margin, 3),
                round(JOINT_BY_NAME["j0"].qmax - self.j0_margin, 3),
            ],
        }

    def _raised(self, q: Sequence[float]) -> bool:
        return (
            abs(float(q[1]) - self.raise_q1) <= self.raise_tol
            and abs(float(q[2]) - self.raise_q2) <= self.raise_tol
            and abs(float(q[3]) - self.raise_q3) <= self.raise_tol
        )

    def _j0_rails(self) -> tuple[float, float]:
        j0 = JOINT_BY_NAME["j0"]
        return j0.qmin + self.j0_margin, j0.qmax - self.j0_margin

    def _advance_el_row(self) -> None:
        if self.el_row >= len(self.el_rows) - 1:
            self.el_row = 0
        else:
            self.el_row += 1
        self._row_samples = 0

    def _pitch_toward(
        self,
        q1: float,
        q2: float,
        q3: float,
        *,
        t1: float,
        t2: float,
        t3: float,
        tol: float,
        move_elbow: bool,
    ) -> dict[str, str]:
        return {
            "j1": _toward("j1", q1, t1, tol=tol),
            "j2": _toward("j2", q2, t2, tol=tol) if move_elbow else "stay",
            "j3": _toward("j3", q3, t3, tol=tol),
        }

    def choices(self, q: Sequence[float]) -> dict[str, str]:
        q0, q1, q2, q3 = (float(q[i]) for i in range(4))
        lo, hi = self._j0_rails()

        if self.phase not in ("stow", "raise", "seek_start", "sweep"):
            self.phase = "stow"

        if self.phase == "stow":
            # Pull tip in toward base Z + yaw to mid-axis (visible retract).
            self.el_row = 0
            pitch = self._pitch_toward(
                q1,
                q2,
                q3,
                t1=self.stow_q1,
                t2=max(self.stow_q2, self.elbow_min_safe),
                t3=self.stow_q3,
                tol=self.stow_tol,
                move_elbow=True,
            )
            j0_ch = _toward("j0", q0, self.stow_j0, tol=self.stow_j0_tol)
            ch = {"j0": j0_ch, **pitch}
            if j0_ch == "stay" and all(pitch[n] == "stay" for n in ("j1", "j2", "j3")):
                self.phase = "raise"
            else:
                return ch

        if self.phase == "raise":
            ch = {
                "j0": "stay",
                **self._pitch_toward(
                    q1,
                    q2,
                    q3,
                    t1=self.raise_q1,
                    t2=self.raise_q2,
                    t3=self.raise_q3,
                    tol=self.raise_tol,
                    move_elbow=True,
                ),
            }
            if all(ch[n] == "stay" for n in ("j1", "j2", "j3")):
                # Pitch row settled — resume sweep from *current* yaw.
                self._seek_done = True
                self.phase = "sweep"
                if not self.visited_j0:
                    self.sweep_dir = 1
                    self.visited_j0.append(q0)
                    self._row_samples = 0
            else:
                return ch

        if self.phase == "seek_start":
            # Legacy path kept for tests; prefer stow→raise→sweep above.
            if abs(q0 - lo) > 0.08:
                return {
                    "j0": "toward_neg_l" if q0 > lo else "toward_pos_l",
                    "j1": "stay",
                    "j2": "stay",
                    "j3": "stay",
                }
            self._seek_done = True
            self.phase = "sweep"
            self.sweep_dir = 1
            self.visited_j0.append(q0)
            self._row_samples = 0

        target = _clamp(q0 + self.sweep_dir * self.step_j0, lo, hi)
        room = (hi - q0) if self.sweep_dir > 0 else (q0 - lo)
        # Soft rail: not enough room for a FOV step → reverse + change pitch.
        if abs(target - q0) < 0.08 or room < 0.12:
            self.visited_j0.append(q0)
            self.sweep_dir *= -1
            self._advance_el_row()
            self.phase = "raise"
            return {
                "j0": "stay",
                **self._pitch_toward(
                    q1,
                    q2,
                    q3,
                    t1=self.raise_q1,
                    t2=self.raise_q2,
                    t3=self.raise_q3,
                    tol=self.raise_tol,
                    move_elbow=False,
                ),
            }

        if not self.visited_j0 or abs(q0 - self.visited_j0[-1]) >= self.step_j0 * 0.5:
            self.visited_j0.append(q0)
            self._row_samples += 1

        # One FOV chunk per tick (always δl).
        j0_ch = "toward_pos_l" if self.sweep_dir > 0 else "toward_neg_l"
        return {
            "j0": j0_ch,
            "j1": "stay",
            "j2": "stay",
            "j3": "stay",
        }



# Tip-cam image yaw vs j0 (Migi USB tip): live logs show face on the LEFT
# (u≈0.1) while the person still lies further in +j0 — the old u↑→+j0 map
# yawed the wrong way and walked past. Use u↑ → −j0.
_YAW_SIGN = -1  # +1 would be textbook; −1 matches tip mount

# Face span (max(bbox)/width) ≈ inverse distance. Live "贴脸" was span≈0.45–0.55.
# Comfortable desk follow often sits at span≈0.20–0.27 — do NOT keep backing there.
_SPAN_COMFORT = 0.20  # hold band lower edge (informational)
_SPAN_CLOSE = 0.32  # start backing off (was 0.28; 0.24–0.27 caused endless retreat)
_SPAN_STUCK = 0.42  # prioritize retract over fine centering
# If shoulder already tucked this far, further "retract" just collapses the arm.
_RETRACT_J1_FLOOR = -0.85
_RETRACT_OPTS = ("stay", "toward_neg_s", "toward_pos_s")
# Allow tiny look-up; reject large pitch swings (bare −j1 dumps the face).
_RETRACT_MAX_LOOK_UP_DEG = 1.5
_RETRACT_MAX_ABS_EL_DEG = 3.5
_RETRACT_RAIL_ROOM = 0.02  # still accept a partial δs into the soft rail


def _apply_choices(q: Sequence[float], choices: dict[str, str]) -> list[float]:
    out: list[float] = []
    for j in JOINTS:
        ch = choices.get(j.name, "stay")
        iv = choice_to_interval(ch, float(q[j.index]), j)
        out.append(waypoint_from_interval(iv, float(q[j.index])))
    return out


def _retract_score(q: Sequence[float], choices: dict[str, str]) -> tuple[float, float]:
    """Return (back_mm along −look, Δelevation_deg). Positive back = retreat."""
    q1 = _apply_choices(q, choices)
    t0, t1 = fk_camera(q), fk_camera(q1)
    z0 = t0[:3, 2] / np.linalg.norm(t0[:3, 2])
    back = float(np.dot(t1[:3, 3] - t0[:3, 3], -z0))
    d_el = float(np.degrees(look_angles(t1)[1] - look_angles(t0)[1]))
    return back, d_el


def _retract_choices(q: Sequence[float]) -> dict[str, str]:
    """Move tip away along look while keeping look nearly level.

    Live failure mode: j2 pegged high → old scorer fell back to bare −j1
    (Δel≈−4.6°), face slid to the bottom of the frame and YuNet dropped.
    Prefer −j1/+j2 (even a partial +j2) or −j1/−j3 over a big pitch dump.
    """
    stay = {j.name: "stay" for j in JOINTS}

    def _opt_ok(name: str, opt: str) -> bool:
        if opt == "stay":
            return True
        j = JOINT_BY_NAME[name]
        qi = float(q[j.index])
        if opt.startswith("toward_neg") and qi - j.qmin < _RETRACT_RAIL_ROOM:
            return False
        if opt.startswith("toward_pos") and j.qmax - qi < _RETRACT_RAIL_ROOM:
            return False
        return True

    best: tuple[float, dict[str, str]] | None = None
    for c1, c2, c3 in product(_RETRACT_OPTS, repeat=3):
        if c1 == c2 == c3 == "stay":
            continue
        if not (_opt_ok("j1", c1) and _opt_ok("j2", c2) and _opt_ok("j3", c3)):
            continue
        ch = {"j0": "stay", "j1": c1, "j2": c2, "j3": c3}
        qn = _apply_choices(q, ch)
        if all(abs(qn[i] - float(q[i])) < 1e-6 for i in range(4)):
            continue
        back, d_el = _retract_score(q, ch)
        if back < 3.0 or d_el > _RETRACT_MAX_LOOK_UP_DEG:
            continue
        if abs(d_el) > _RETRACT_MAX_ABS_EL_DEG:
            continue
        # Heavy |Δel| penalty; extra cost for look-up (user-visible raise).
        score = back - 2.5 * abs(d_el) - 1.0 * max(0.0, d_el)
        if best is None or score > best[0]:
            best = (score, ch)
    if best is not None:
        return best[1]

    # Last resort: any retreat that does not look up much (may dive a bit).
    loose: tuple[float, dict[str, str]] | None = None
    for c1, c2, c3 in product(_RETRACT_OPTS, repeat=3):
        if c1 == c2 == c3 == "stay":
            continue
        if not (_opt_ok("j1", c1) and _opt_ok("j2", c2) and _opt_ok("j3", c3)):
            continue
        ch = {"j0": "stay", "j1": c1, "j2": c2, "j3": c3}
        back, d_el = _retract_score(q, ch)
        if back < 3.0 or d_el > _RETRACT_MAX_LOOK_UP_DEG:
            continue
        score = back - 2.5 * abs(d_el) - 1.0 * max(0.0, d_el)
        if loose is None or score > loose[0]:
            loose = (score, ch)
    return loose[1] if loose is not None else stay


def follow_choices(
    presence: Presence,
    q: Sequence[float],
    *,
    deadzone: float = 0.08,
    center_deadzone: float = 0.06,
) -> dict[str, str]:
    """Keep face in frame at a comfortable distance (span band).

    Priority: (1) back off only when truly close (span≥CLOSE), (2) yaw,
    (3) pitch when distance is OK. Do not keep retreating in the comfort band
    — live span≈0.24–0.27 is normal desk follow and used to walk the arm out.
    """
    if not presence.present or presence.u is None or presence.v is None:
        return {j.name: "stay" for j in JOINTS}

    u, v = presence.u, presence.v
    err_u, err_v = u - 0.5, v - 0.5
    span = float(presence.span) if presence.span is not None else 0.0
    too_close = span >= _SPAN_CLOSE
    face_stuck = span >= _SPAN_STUCK
    q1 = float(q[1])
    already_tucked = q1 <= _RETRACT_J1_FLOOR
    ch = {j.name: "stay" for j in JOINTS}
    retracting = False

    def _do_retract() -> dict[str, str]:
        # Shoulder already hard-tucked: further FK "back" collapses pose and
        # barely shrinks span (live endless j2−/j3− at j1≈−1.07).
        if already_tucked and not face_stuck:
            return {j.name: "stay" for j in JOINTS}
        return _retract_choices(q)

    # Very close: retract first (even if a bit off-center) so we don't glue on.
    if face_stuck and abs(err_u) <= 0.22:
        ch = _do_retract()
        retracting = any(ch[n] not in ("stay", "widen_stay") for n in ("j1", "j2", "j3"))
    elif abs(err_u) > deadzone:
        want_pos = (err_u * _YAW_SIGN) > 0
        ch["j0"] = "toward_pos_s" if want_pos else "toward_neg_s"
    elif too_close:
        ch = _do_retract()
        retracting = any(ch[n] not in ("stay", "widen_stay") for n in ("j1", "j2", "j3"))
    elif abs(err_v) > deadzone:
        # Image v↑ (face low) → tip look down (live tip-mount map).
        if err_v > 0:
            ch["j1"] = "toward_pos_s"
            ch["j3"] = "toward_neg_s"
        else:
            ch["j1"] = "toward_neg_s"
            ch["j3"] = "toward_pos_s"
    elif abs(err_u) <= center_deadzone and abs(err_v) <= center_deadzone:
        ch = {j.name: "widen_stay" for j in JOINTS}

    for name, choice in list(ch.items()):
        if choice in ("stay", "widen_stay"):
            continue
        # Retract combos are pre-filtered for rail room; stripping one joint
        # (e.g. leaving bare +j2) would look up again.
        if retracting and name != "j0":
            continue
        j = JOINT_BY_NAME[name]
        qi = float(q[j.index])
        if choice.startswith("toward_neg") and qi - j.qmin < 0.08:
            ch[name] = "stay"
        if choice.startswith("toward_pos") and j.qmax - qi < 0.08:
            ch[name] = "stay"
    return ch


def _coast_from_last_u(last_u: float | None) -> dict[str, str]:
    """Keep nudging yaw toward last known face while YuNet flickers."""
    ch = {j.name: "stay" for j in JOINTS}
    if last_u is None:
        return ch
    err = last_u - 0.5
    if abs(err) < 0.06:
        return ch
    want_pos = (err * _YAW_SIGN) > 0
    ch["j0"] = "toward_pos_s" if want_pos else "toward_neg_s"
    return ch


def choices_to_q_star(q: Sequence[float], choices: dict[str, str]) -> list[float]:
    out: list[float] = []
    for j in JOINTS:
        ch = choices.get(j.name, "stay")
        iv = choice_to_interval(ch, float(q[j.index]), j)
        out.append(waypoint_from_interval(iv, float(q[j.index])))
    return out


@dataclass
class MissionController:
    """Traverse ↔ Follow on presence, gated by Op.

    After a brief face lock is lost, enter *reacquire*: zig-zag around the
    last hit yaw instead of resuming a full ±π sweep that walks past the person.
    """

    mode: str = "traverse"  # traverse | follow | reacquire
    miss_streak: int = 0
    miss_limit: int = 4  # YuNet flickers; 2 was flipping follow↔reacquire too fast
    traverse: TraversePlanner = field(default_factory=TraversePlanner)
    target_id: int | None = None
    allow_traverse: bool = True
    last_u: float | None = None
    last_v: float | None = None
    last_j0: float | None = None
    # Local search after losing a face (radians / ticks).
    reacq_amp: float = 0.30
    reacq_max_ticks: int = 10
    reacq_center: float | None = None
    reacq_dir: int = 1
    reacq_ticks: int = 0

    def reset(self) -> None:
        self.mode = "traverse" if self.allow_traverse else "follow"
        self.miss_streak = 0
        self.last_u = None
        self.last_v = None
        self.last_j0 = None
        self.reacq_center = None
        self.reacq_ticks = 0
        self.traverse.reset()

    def _relevant(self, presence: Presence) -> bool:
        if not presence.present:
            return False
        if self.target_id is None:
            return True
        return presence.face_id == self.target_id

    def _enter_reacquire(self, q: Sequence[float]) -> None:
        self.mode = "reacquire"
        self.reacq_center = float(self.last_j0 if self.last_j0 is not None else q[0])
        # Same map as follow: face left of center → first step with _YAW_SIGN.
        if self.last_u is not None:
            err = self.last_u - 0.5
            self.reacq_dir = 1 if (err * _YAW_SIGN) > 0 else -1
        else:
            self.reacq_dir = 1
        self.reacq_ticks = 0

    def _reacquire_choices(self, q: Sequence[float]) -> dict[str, str]:
        j0 = JOINT_BY_NAME["j0"]
        q0 = float(q[0])
        center = float(self.reacq_center if self.reacq_center is not None else q0)
        lo = max(j0.qmin + 0.08, center - self.reacq_amp)
        hi = min(j0.qmax - 0.08, center + self.reacq_amp)
        target = _clamp(center + self.reacq_dir * self.reacq_amp, lo, hi)
        if abs(q0 - target) < 0.08:
            self.reacq_dir *= -1
            target = _clamp(center + self.reacq_dir * self.reacq_amp, lo, hi)
        self.reacq_ticks += 1
        # Always δs — δl inside the ±amp window overshoots the person.
        if abs(target - q0) <= 0.04:
            j0_ch = "stay"
        elif target > q0:
            j0_ch = "toward_pos_s"
        else:
            j0_ch = "toward_neg_s"
        return {"j0": j0_ch, "j1": "stay", "j2": "stay", "j3": "stay"}

    def step(self, presence: Presence, q: Sequence[float]) -> dict[str, Any]:
        hit = self._relevant(presence)
        if hit:
            self.miss_streak = 0
            self.last_u = presence.u
            self.last_v = presence.v
            self.last_j0 = float(q[0])
            self.mode = "follow"
            choices = follow_choices(presence, q)
        elif self.mode == "reacquire" and self.allow_traverse:
            if self.reacq_ticks >= self.reacq_max_ticks:
                # Give up local search; stow to mid-axis then full sweep.
                self.mode = "traverse"
                self.traverse.begin_global_search()
                choices = self.traverse.choices(q)
            else:
                choices = self._reacquire_choices(q)
        else:
            self.miss_streak += 1
            if self.mode == "follow" and self.miss_streak >= self.miss_limit:
                if self.allow_traverse:
                    self._enter_reacquire(q)
                    choices = self._reacquire_choices(q)
                else:
                    choices = _coast_from_last_u(self.last_u)
                    self.mode = "follow"
            elif self.mode == "follow" or not self.allow_traverse:
                # One tick of coast only, then hold — avoid walking past the person.
                if self.miss_streak <= 1:
                    choices = _coast_from_last_u(self.last_u)
                else:
                    choices = {j.name: "stay" for j in JOINTS}
                if not self.allow_traverse:
                    self.mode = "follow"
            else:
                self.mode = "traverse"
                choices = self.traverse.choices(q)

        q_star = choices_to_q_star(q, choices)
        moved = any(abs(a - b) > 1e-4 for a, b in zip(q_star, q))
        return {
            "mode": self.mode,
            "miss_streak": self.miss_streak,
            "choices": choices,
            "q_star": q_star,
            "moved": moved,
            "traverse": self.traverse.as_dict(),
            "presence": presence.as_dict(),
            "target_id": self.target_id,
            "hit": hit,
            "last_u": self.last_u,
            "last_j0": self.last_j0,
            "reacq": {
                "center": self.reacq_center,
                "dir": self.reacq_dir,
                "ticks": self.reacq_ticks,
                "amp": self.reacq_amp,
            },
        }
