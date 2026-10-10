"""One decision tick: scene → parallel JEV → intervals → optional one stream."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Sequence

from .interval import Interval, choice_to_interval, waypoint_from_interval
from .jev_client import JevClient, JevError
from .mech import CHOICES, CRITERIA, JOINTS
from .search import SearchSnapshot
from .state import (
    best_missing_choice,
    build_state,
    choice_streaks,
    joint_instructions,
    target_status,
)


JudgeFn = Callable[[str, str], dict]

_LIMIT_ROOM = 0.08
_STREAK_FLIP = 4  # only for pitch dither; j0 sweep is one-way via want_az


@dataclass
class DecisionTick:
    t: float
    goal: str
    scene: str
    scene_age_ms: float
    q_before: list[float]
    choices: dict[str, str]
    intervals: dict[str, tuple[float, float]]
    q_star: list[float]
    moved: bool
    stream_status: str | None = None
    q_after: list[float] | None = None
    reached: dict[str, bool] = field(default_factory=dict)
    jev_ms: dict[str, float] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    search: dict[str, Any] | None = None

    def to_hist(self) -> dict[str, Any]:
        return {
            "t": round(self.t, 2),
            "scene_short": (self.scene or "")[:120],
            "choices": dict(self.choices),
            "q_star": [round(x, 3) for x in self.q_star],
            "reached": dict(self.reached),
            "moved": self.moved,
            "search": self.search,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _flip_choice(ch: str) -> str:
    if "neg" in ch:
        return ch.replace("neg", "pos")
    if "pos" in ch:
        return ch.replace("pos", "neg")
    return "toward_pos_s"


def sanitize_choice(
    joint_name: str,
    q: float,
    choice: str,
    *,
    status: str,
    hist: Sequence[dict[str, Any]],
    q_all: Sequence[float] | None = None,
    search: SearchSnapshot | None = None,
) -> str:
    j = next(x for x in JOINTS if x.name == joint_name)
    ch = choice if choice in CHOICES else "stay"
    room_neg = float(q) - j.qmin
    room_pos = j.qmax - float(q)
    q_vec = list(q_all) if q_all is not None else [0.0, 0.0, 0.0, 0.0]
    if len(q_vec) == 4:
        q_vec[j.index] = float(q)

    phase = search.phase if search else "raise"

    if status == "MISSING":
        if ch in ("stay", "widen_stay"):
            # raise: j0 stay OK; sweep: j0 must not stay
            if phase == "raise" and joint_name == "j0":
                return "stay"
            if phase == "sweep" and joint_name in ("j1", "j2", "j3") and search is not None and abs(search.err_el) < 0.2:
                return "stay"
            ch = best_missing_choice(joint_name, q_vec, search)
        elif phase == "sweep" and joint_name == "j0":
            # Force yaw toward want_az — override dither opposite to err
            forced = best_missing_choice("j0", q_vec, search)
            if forced != "stay":
                ch = forced

    if ch.startswith("toward_neg") and room_neg < _LIMIT_ROOM:
        if status == "MISSING" and room_pos > _LIMIT_ROOM:
            return "toward_pos_s"
        return "stay"
    if ch.startswith("toward_pos") and room_pos < _LIMIT_ROOM:
        if status == "MISSING" and room_neg > _LIMIT_ROOM:
            return "toward_neg_s"
        return "stay"

    # Streak flip only on pitch links (not j0 — sweep is unidirectional).
    if (
        status == "MISSING"
        and joint_name != "j0"
        and ch.startswith("toward_")
        and phase != "sweep"
    ):
        streaks = choice_streaks(hist)
        prev_ch, n = streaks.get(joint_name, ("", 0))
        same_sign = ("neg" in prev_ch and "neg" in ch) or ("pos" in prev_ch and "pos" in ch)
        if same_sign and n >= _STREAK_FLIP:
            flipped = _flip_choice(ch)
            if flipped.startswith("toward_neg") and room_neg < _LIMIT_ROOM:
                return best_missing_choice(joint_name, q_vec, search)
            if flipped.startswith("toward_pos") and room_pos < _LIMIT_ROOM:
                return best_missing_choice(joint_name, q_vec, search)
            return flipped

    return ch


def _heuristic_judge(joint_name: str, state: str) -> dict:
    low = state.lower()
    choice = "stay"
    if joint_name == "j0":
        if "left-" in low:
            choice = "toward_neg_s"
        if "right-" in low:
            choice = "toward_pos_s"
        if "center-" in low and "face@" in low:
            choice = "stay"
    elif joint_name == "j3":
        if "upper" in low:
            choice = "toward_pos_s"
        if "lower" in low:
            choice = "toward_neg_s"
    return {
        "choice": choice,
        "probabilities": {c: (1.0 if c == choice else 0.0) for c in CHOICES},
        "confidence": 0.2,
        "invalid_choice": False,
        "latency_ms": 0.0,
        "model": "heuristic",
    }


def make_jev_judge(client: JevClient) -> JudgeFn:
    def _judge(joint_name: str, state: str) -> dict:
        return client.choose(
            state=state,
            question_id=f"joint_{joint_name}",
            instructions=joint_instructions(joint_name),
            criteria=CRITERIA,
        )

    return _judge


def parallel_judge(state: str, judge: JudgeFn) -> tuple[dict[str, dict], dict[str, str]]:
    results: dict[str, dict] = {}
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=len(JOINTS)) as pool:
        futs = {pool.submit(judge, j.name, state): j.name for j in JOINTS}
        for fut in as_completed(futs):
            name = futs[fut]
            try:
                results[name] = fut.result()
            except Exception as exc:  # noqa: BLE001
                errors[name] = str(exc)
                results[name] = {
                    "choice": "stay",
                    "probabilities": {},
                    "confidence": 0.0,
                    "invalid_choice": True,
                    "latency_ms": 0.0,
                    "model": None,
                }
    return results, errors


def synthesize(
    q: Sequence[float],
    judged: dict[str, dict],
    *,
    hist: Sequence[dict[str, Any]] | None = None,
    status: str = "UNSPECIFIED",
    search: SearchSnapshot | None = None,
) -> tuple[dict[str, str], dict[str, Interval], list[float], bool]:
    choices: dict[str, str] = {}
    intervals: dict[str, Interval] = {}
    q_star: list[float] = []
    need_move = False
    hist = hist or []
    for j, qj in zip(JOINTS, q):
        raw = judged.get(j.name) or {}
        ch = raw.get("choice") if raw.get("choice") in CHOICES else "stay"
        if raw.get("invalid_choice") and ch not in CHOICES:
            ch = "stay"
        ch = sanitize_choice(
            j.name,
            float(qj),
            str(ch),
            status=status,
            hist=hist,
            q_all=q,
            search=search,
        )
        choices[j.name] = str(ch)
        iv = choice_to_interval(ch, float(qj), j)
        intervals[j.name] = iv
        wp = waypoint_from_interval(iv, float(qj))
        q_star.append(wp)
        if abs(wp - float(qj)) > 1e-4:
            need_move = True
    return choices, intervals, q_star, need_move


def run_tick(
    *,
    goal: str,
    q_before: Sequence[float],
    scene: str,
    scene_age_ms: float,
    hist: list[dict[str, Any]],
    judge: JudgeFn | None = None,
    dry_run: bool = False,
    arm: Any | None = None,
    spd: int = 220,
    settle_s: float = 0.5,
    stream_wait_s: float = 18.0,
    search: SearchSnapshot | None = None,
) -> DecisionTick:
    if judge is None:
        judge = _heuristic_judge
    status = target_status(goal, scene)
    state = build_state(
        goal=goal,
        scene=scene,
        scene_age_ms=scene_age_ms,
        q=q_before,
        hist=hist,
        search=search,
    )
    judged, errors = parallel_judge(state, judge)
    choices, intervals, q_star, need_move = synthesize(
        q_before, judged, hist=hist, status=status, search=search
    )
    jev_ms = {k: float((judged.get(k) or {}).get("latency_ms") or 0.0) for k in choices}

    tick = DecisionTick(
        t=time.time(),
        goal=goal,
        scene=scene,
        scene_age_ms=scene_age_ms,
        q_before=[float(x) for x in q_before],
        choices=choices,
        intervals={k: (v.lo, v.hi) for k, v in intervals.items()},
        q_star=q_star,
        moved=False,
        errors=errors,
        jev_ms=jev_ms,
        search=search.as_dict() if search else None,
    )

    if dry_run or arm is None or not need_move:
        tick.stream_status = "skipped"
        tick.q_after = list(tick.q_before)
        tick.reached = {
            j.name: intervals[j.name].contains(tick.q_before[j.index]) for j in JOINTS
        }
        return tick

    t_stream = time.perf_counter()
    st = arm.stream(q_star, spd, wait_s=stream_wait_s)
    stream_s = time.perf_counter() - t_stream
    tick.stream_status = f"{st}({stream_s:.1f}s)"
    tick.moved = True
    time.sleep(max(0.0, settle_s))
    tick.q_after = [float(x) for x in q_star]
    tick.reached = {
        j.name: intervals[j.name].contains(tick.q_after[j.index]) for j in JOINTS
    }
    return tick


def bind_live_judge() -> JudgeFn:
    try:
        return make_jev_judge(JevClient())
    except JevError:
        raise
