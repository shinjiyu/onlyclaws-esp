"""Slow fixed-period servo loop (JEV or presence mission)."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .arm_cloud import ArmCloud
from .arm_usb import ArmUsb, find_port
from .fk import fk_camera, look_angles
from .mission import MissionController
from .presence import presence_from_scene
from .search import SearchPlanner
from .state import goal_is_person, target_status
from .tick import DecisionTick, bind_live_judge, run_tick, _heuristic_judge
from .vision_snap import snap_scene

EmitFn = Callable[[str, dict[str, Any]], None]



def open_arm(transport: str, port: str | None = None):
    t = (transport or "usb").lower()
    if t == "cloud":
        arm = ArmCloud()
        print("arm transport=cloud", flush=True)
        return arm
    if t == "usb":
        p = port or find_port()
        arm = ArmUsb(p)
        print(f"arm transport=usb port={p}", flush=True)
        return arm
    raise ValueError(f"unknown transport {transport!r} (use usb|cloud)")


def _sleep_interruptible(seconds: float, stop_event: threading.Event | None) -> bool:
    """Sleep up to `seconds`. Return True if stop was requested."""
    if seconds <= 0:
        return bool(stop_event and stop_event.is_set())
    if stop_event is None:
        time.sleep(seconds)
        return False
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        if stop_event.is_set():
            return True
        time.sleep(min(0.05, end - time.perf_counter()))
    return stop_event.is_set()


def _resolve_mode(mode: str | None, goal: str, *, has_op: bool) -> str:
    m = (mode or "auto").lower().strip()
    if m == "auto":
        if has_op or goal_is_person(goal):
            return "presence"
        return "jev"
    if m in ("presence", "jev"):
        return m
    raise ValueError(f"unknown mode {mode!r} (use auto|presence|jev)")


def run_loop(
    *,
    goal: str | None = None,
    op: str | None = None,
    face_id: int | None = None,
    ticks: int | None = 5,
    t_dec: float = 0.0,
    spd: int = 220,
    settle_s: float | None = None,
    hist_w: int = 6,
    dry_run: bool = False,
    no_arm: bool = False,
    image: str | None = None,
    scene_override: str | None = None,
    log_dir: str | Path | None = None,
    feedback_every: int | None = None,
    stream_wait_s: float = 18.0,
    transport: str = "usb",
    port: str | None = None,
    stop_event: threading.Event | None = None,
    on_event: EmitFn | None = None,
    mode: str | None = "auto",
    identify: bool = True,
    gallery_dir: str | Path | None = None,
) -> list[DecisionTick]:
    """Run pathway-C ticks.

    Presence ops (preferred): op=find_any|find_id|follow, optional face_id.
    Legacy: goal text + mode=jev|auto.
    """
    from .ops import Op, parse_op

    parsed: Op | None = None
    if op:
        parsed = parse_op(op, face_id)
    goal_text = (goal or "").strip()
    if parsed is None and not goal_text:
        parsed = parse_op("find_any")
        goal_text = parsed.label()
    elif parsed is not None:
        goal_text = goal_text or parsed.label()

    resolved = _resolve_mode(mode, goal_text, has_op=parsed is not None)
    if resolved == "presence" and parsed is None:
        # Natural-language goal → default find_any
        parsed = parse_op("find_any", face_id)

    use_usb = (transport or "usb").lower() == "usb"
    if settle_s is None:
        # Presence: short settle — tip cam FOV steps are large; don't wait 0.8s/tick.
        settle_s = 0.35 if (use_usb and resolved == "presence") else (0.8 if use_usb else 0.5)
    if feedback_every is None:
        feedback_every = 1 if use_usb else 0

    unlimited = ticks is None or ticks <= 0
    arm = None if (dry_run or no_arm) else open_arm(transport, port)

    hist: list[dict[str, Any]] = []
    out: list[DecisionTick] = []
    log_path = Path(log_dir) if log_dir else None
    if log_path:
        log_path.mkdir(parents=True, exist_ok=True)

    q_cache: list[float] | None = None
    planner = SearchPlanner()
    mission = MissionController()
    if parsed is not None:
        mission.target_id = parsed.target_id
        mission.allow_traverse = parsed.name != "follow"
        if not mission.allow_traverse:
            mission.mode = "follow"
    gallery = None
    do_identify = bool(identify) and resolved == "presence"
    if do_identify:
        from vision.identity import FaceGallery, sface_available

        gallery = FaceGallery(gallery_dir) if gallery_dir else FaceGallery()
        print(
            f"face gallery {gallery.json_path} n={len(gallery.records)} "
            f"sface={sface_available()}",
            flush=True,
        )
    judge = None
    if resolved == "jev":
        judge = _heuristic_judge if dry_run else bind_live_judge()

    def emit(kind: str, **payload: Any) -> None:
        if on_event is not None:
            on_event(kind, payload)
        line = payload.get("line")
        if line is not None:
            print(line, flush=True)

    op_label = parsed.label() if parsed else goal_text
    try:
        i = 0
        while True:
            if stop_event is not None and stop_event.is_set():
                emit("stopped", line="stop requested — leaving loop", tick_index=i)
                break
            if not unlimited and i >= int(ticks):
                break

            t_start = time.perf_counter()
            label = "∞" if unlimited else str(ticks)
            emit(
                "tick_start",
                line=f"\n=== tick {i + 1}/{label}  mode={resolved} op={op_label} ===",
                tick_index=i,
                goal=goal_text,
                op=parsed.as_dict() if parsed else None,
                mode=resolved,
            )

            if scene_override is not None:
                scene, age = scene_override, 0.0
                emit("scene", line=f"scene(override): {scene}", scene=scene, age_ms=age)
            else:
                perceive = "person" if (resolved == "presence" or goal_is_person(goal_text)) else "full"
                save = None
                if log_path:
                    save = log_path / f"tick_{i:03d}_vis.jpg"
                snap = snap_scene(
                    image=image,
                    perceive=perceive,
                    save_path=save,
                    identify=do_identify,
                    gallery=gallery,
                )
                scene, age = snap["state"], float(snap["age_ms"])
                emit(
                    "scene",
                    line=(
                        f"scene({snap['source']} perceive={snap.get('perceive')} "
                        f"id={snap.get('identify')} "
                        f"{snap['width']}x{snap['height']} vis={snap['ms']:.0f}ms): {scene}"
                    ),
                    scene=scene,
                    age_ms=age,
                    vis_ms=snap["ms"],
                    source=snap["source"],
                    perceive=snap.get("perceive"),
                    face_ids=snap.get("face_ids") or [],
                )

            need_fb = arm is not None and (
                q_cache is None
                or (feedback_every > 0 and i % feedback_every == 0)
            )
            if arm is not None and need_fb:
                t_fb = time.perf_counter()
                q = arm.feedback()
                q_cache = list(q)
                emit(
                    "q",
                    line=(
                        f"q_before(feedback {(time.perf_counter()-t_fb)*1000:.0f}ms): "
                        f"{[round(x, 3) for x in q]}"
                    ),
                    q=[round(x, 3) for x in q],
                )
            elif q_cache is not None:
                q = list(q_cache)
                emit(
                    "q",
                    line=f"q_before(cache): {[round(x, 3) for x in q]}",
                    q=[round(x, 3) for x in q],
                )
            else:
                q = [-0.09, 0.35, 2.15, 3.90]
                emit("q", line=f"q(fake): {q}", q=q)

            if resolved == "presence":
                tick = _presence_tick(
                    goal=goal_text,
                    q=q,
                    scene=scene,
                    age=age,
                    mission=mission,
                    arm=arm,
                    spd=spd,
                    settle_s=settle_s,
                    stream_wait_s=0.0 if use_usb else stream_wait_s,
                    dry_run=dry_run or arm is None,
                    use_usb=use_usb,
                    emit=emit,
                )
            else:
                status = target_status(goal_text, scene)
                az, el, _, _ = look_angles(fk_camera(q))
                search_snap = planner.update(look_az=az, look_el=el, status=status)
                emit(
                    "search",
                    line=(
                        f"search phase={search_snap.phase} "
                        f"want_az={search_snap.want_az:.3f} want_el={search_snap.want_el:.3f} "
                        f"err_az={search_snap.err_az:+.3f} err_el={search_snap.err_el:+.3f} "
                        f"dir={search_snap.sweep_dir:+d} visited={search_snap.visited_n}"
                    ),
                    **search_snap.as_dict(),
                )
                assert judge is not None
                tick = run_tick(
                    goal=goal_text,
                    q_before=q,
                    scene=scene,
                    scene_age_ms=age,
                    hist=hist[-hist_w:],
                    judge=judge,
                    dry_run=dry_run or arm is None,
                    arm=arm,
                    spd=spd,
                    settle_s=settle_s,
                    stream_wait_s=0.0 if use_usb else stream_wait_s,
                    search=search_snap,
                )
                emit(
                    "choices",
                    line=(
                        f"choices={tick.choices} q*={[round(x, 3) for x in tick.q_star]} "
                        f"moved={tick.moved} stream={tick.stream_status} "
                        f"jev_ms={tick.jev_ms} errors={tick.errors or '-'}"
                    ),
                    choices=tick.choices,
                    q_star=[round(x, 3) for x in tick.q_star],
                    moved=tick.moved,
                    stream=tick.stream_status,
                    jev_ms=tick.jev_ms,
                    errors=tick.errors or {},
                )

            if tick.q_after is not None:
                if arm is not None and use_usb and tick.moved:
                    try:
                        tick.q_after = arm.feedback()
                    except Exception as exc:  # noqa: BLE001
                        tick.errors["post_fb"] = str(exc)
                emit(
                    "q_after",
                    line=(
                        f"q_after: {[round(x, 3) for x in tick.q_after]} "
                        f"reached={tick.reached}"
                    ),
                    q_after=[round(x, 3) for x in tick.q_after],
                    reached=tick.reached,
                )
                q_cache = list(tick.q_after)

            hist.append(tick.to_hist())
            out.append(tick)
            if log_path:
                (log_path / f"tick_{i:03d}.json").write_text(
                    json.dumps(tick.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

            elapsed = time.perf_counter() - t_start
            emit(
                "tick_done",
                line=f"tick_wall={elapsed:.1f}s",
                tick_index=i,
                wall_s=elapsed,
                tick=tick.to_dict(),
            )

            i += 1
            if not unlimited and i >= int(ticks):
                break
            sleep_for = t_dec - elapsed
            if sleep_for > 0:
                emit("sleep", line=f"sleep {sleep_for:.1f}s until next decision")
                if _sleep_interruptible(sleep_for, stop_event):
                    emit("stopped", line="stop requested during pad", tick_index=i)
                    break
    finally:
        close = getattr(arm, "close", None)
        if callable(close):
            close()
        emit("closed", line="arm closed" if arm is not None else "done")

    return out


def _presence_tick(
    *,
    goal: str,
    q: list[float],
    scene: str,
    age: float,
    mission: MissionController,
    arm: Any,
    spd: int,
    settle_s: float,
    stream_wait_s: float,
    dry_run: bool,
    use_usb: bool,
    emit: EmitFn,
) -> DecisionTick:
    from .interval import choice_to_interval
    from .mech import JOINT_BY_NAME

    presence = presence_from_scene(scene)
    step = mission.step(presence, q)
    emit(
        "presence",
        line=(
            f"presence present={presence.present} "
            f"face_id={presence.face_id} name={presence.name!r} "
            f"hit={step.get('hit')} target_id={step.get('target_id')} "
            f"u={presence.u} v={presence.v} mode={step['mode']} "
            f"miss={step['miss_streak']} traverse={step['traverse']['phase']} "
            f"visited_j0={step['traverse']['visited_n']}"
        ),
        presence=step["presence"],
        mode=step["mode"],
        miss_streak=step["miss_streak"],
        traverse=step["traverse"],
        hit=step.get("hit"),
        target_id=step.get("target_id"),
    )
    choices = step["choices"]
    q_star = list(step["q_star"])
    moved = bool(step["moved"])
    stream_status = None
    errors: dict[str, str] = {}
    q_after = list(q)
    if moved and not dry_run and arm is not None:
        try:
            stream_status = arm.stream(q_star, spd=spd, wait_s=stream_wait_s)
            if settle_s > 0:
                time.sleep(settle_s)
            q_after = list(q_star)
        except Exception as exc:  # noqa: BLE001
            errors["stream"] = str(exc)
            stream_status = "error"
            moved = False
    elif moved and dry_run:
        stream_status = "dry_run"
        q_after = list(q_star)

    emit(
        "choices",
        line=(
            f"choices={choices} q*={[round(x, 3) for x in q_star]} "
            f"moved={moved} stream={stream_status} errors={errors or '-'}"
        ),
        choices=choices,
        q_star=[round(x, 3) for x in q_star],
        moved=moved,
        stream=stream_status,
        errors=errors,
    )

    intervals = {
        name: (
            round(
                choice_to_interval(
                    ch, float(q[JOINT_BY_NAME[name].index]), JOINT_BY_NAME[name]
                ).lo,
                4,
            ),
            round(
                choice_to_interval(
                    ch, float(q[JOINT_BY_NAME[name].index]), JOINT_BY_NAME[name]
                ).hi,
                4,
            ),
        )
        for name, ch in choices.items()
    }

    return DecisionTick(
        t=time.time(),
        goal=goal,
        scene=scene,
        scene_age_ms=age,
        q_before=list(q),
        choices=choices,
        intervals=intervals,
        q_star=q_star,
        moved=moved,
        stream_status=stream_status,
        q_after=q_after,
        reached={},
        jev_ms={},
        errors=errors,
        search={
            "mission": step["mode"],
            "presence": step["presence"],
            "traverse": step["traverse"],
            "miss_streak": step["miss_streak"],
        },
    )
