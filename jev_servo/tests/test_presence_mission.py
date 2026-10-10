"""Unit tests for presence + traverse/follow mission."""

from __future__ import annotations

import pytest

from jev_servo.mission import MissionController, TraversePlanner, follow_choices
from jev_servo.presence import presence_from_scene


def test_presence_missing():
    p = presence_from_scene("tv@0.5,0.5; chair@0.2,0.8")
    assert p.present is False
    assert p.u is None


def test_presence_face():
    p = presence_from_scene("face@0.62,0.41 span=0.2 center-mid s=0.9")
    assert p.present is True
    assert abs(p.u - 0.62) < 1e-6
    assert abs(p.v - 0.41) < 1e-6


def test_presence_ignores_coco_person():
    p = presence_from_scene("person@0.50,0.50 span=0.99 center-mid s=0.66")
    assert p.present is False


def test_traverse_stows_tip_in_then_raises_then_sweeps():
    """Entering search must visibly retract (j1↓) before yaw sweep."""
    tp = TraversePlanner()
    q = [1.97, 0.224, 2.465, 3.924]  # live log: only j0 moved under old stow
    ch1 = tp.choices(q)
    assert tp.phase == "stow"
    assert ch1["j1"].startswith("toward_neg"), ch1  # pull tip in
    assert ch1["j0"].startswith("toward_neg")  # toward mid-axis

    q_stowed = [0.05, tp.stow_q1, tp.stow_q2, tp.stow_q3]
    ch2 = tp.choices(q_stowed)
    assert tp.phase == "raise"
    assert ch2["j0"] == "stay"
    assert ch2["j1"].startswith("toward_pos"), ch2  # extend to look-up row

    q_ready = [0.05, tp.raise_q1, tp.raise_q2, tp.raise_q3]
    ch3 = tp.choices(q_ready)
    assert tp.phase == "sweep"
    assert ch3["j0"] == "toward_pos_l"
    assert ch3["j1"] == "stay"


def test_traverse_advances_elevation_at_rail():
    tp = TraversePlanner()
    lo, hi = tp._j0_rails()
    tp.phase = "sweep"
    tp._seek_done = True
    tp.sweep_dir = 1
    tp.el_row = 0
    q_hi = [hi - 0.01, tp.raise_q1, tp.raise_q2, tp.raise_q3]
    ch = tp.choices(q_hi)
    assert tp.el_row == 1
    assert tp.phase == "raise"
    assert tp.sweep_dir == -1
    assert ch["j0"] == "stay"


def test_reacquire_timeout_restows_before_sweep():
    m = MissionController(miss_limit=1, reacq_max_ticks=2)
    q = [1.52, 0.14, 2.4, 4.4]
    from jev_servo.presence import Presence

    m.step(Presence(present=True, u=0.5, v=0.5, span=0.15), q)
    m.step(Presence(present=False), q)  # miss → reacquire (limit=1)
    assert m.mode == "reacquire"
    m.step(Presence(present=False), q)  # reacq tick 1
    s = m.step(Presence(present=False), [2.0, -0.3, 2.4, 4.1])  # tick 2 → timeout
    assert s["mode"] == "traverse"
    assert s["traverse"]["phase"] == "stow"
    assert s["choices"]["j0"] != "stay" or s["choices"]["j1"] != "stay"


def test_follow_pitch_face_high_in_frame_looks_up_image():
    """Face near top (v small) must not use the old j1+/j3− which dives further."""
    from jev_servo.presence import Presence

    q = [2.75, 0.30, 2.40, 4.00]
    p = Presence(present=True, u=0.50, v=0.15, span=0.20)
    ch = follow_choices(p, q)
    assert ch["j0"] == "stay"
    assert ch["j1"] == "toward_neg_s"
    assert ch["j3"] == "toward_pos_s"


def test_follow_yaw_inverted_for_tip_cam():
    from jev_servo.presence import Presence

    q = [0.0, 0.25, 1.85, 3.55]
    ch = follow_choices(Presence(present=True, u=0.80, v=0.50, span=0.12), q)
    assert ch["j0"] == "toward_neg_s"
    assert ch["j1"] == "stay"


def test_el_rows_ordered_by_true_look_up():
    from jev_servo.fk import fk_camera, look_angles
    from jev_servo.mission import TraversePlanner

    tp = TraversePlanner()
    els = []
    for q1, q3 in tp.el_rows:
        _az, el, *_ = look_angles(fk_camera([0.0, q1, tp.raise_q2, q3]))
        els.append(el)
    assert els[0] > els[-1]  # first row looks higher than last
    assert els[0] > 0.2  # start clearly above horizon


def test_follow_retracts_when_face_too_close():
    from jev_servo.presence import Presence

    q = [2.65, 0.30, 2.30, 3.90]
    p = Presence(present=True, u=0.50, v=0.50, span=0.50)
    ch = follow_choices(p, q)
    assert ch["j0"] == "stay"
    # Level retract: −j1 compensated by +j2 (not bare +j2 look-up).
    assert ch["j1"] == "toward_neg_s"
    assert ch["j2"] == "toward_pos_s"


def test_follow_holds_in_comfort_span_band():
    """Live bug: span≈0.25 kept calling retract until j1≈−1.07."""
    from jev_servo.presence import Presence

    q = [2.09, -0.50, 2.0, 3.2]
    p = Presence(present=True, u=0.50, v=0.50, span=0.26)
    ch = follow_choices(p, q)
    assert ch["j1"] in ("stay", "widen_stay")
    assert ch["j2"] in ("stay", "widen_stay")
    assert all(ch[n] in ("stay", "widen_stay") for n in ("j1", "j2", "j3"))


def test_follow_stops_retract_when_shoulder_already_tucked():
    from jev_servo.presence import Presence

    q = [2.09, -1.07, 1.55, 1.66]  # live endless-back pose
    p = Presence(present=True, u=0.50, v=0.50, span=0.33)  # above CLOSE, below STUCK
    ch = follow_choices(p, q)
    assert ch["j1"] == "stay"
    assert ch["j2"] == "stay"
    assert ch["j3"] == "stay"


def test_retract_backs_along_look_without_looking_up():
    """FK check: retract retreats along look and must not raise elevation."""
    from jev_servo.fk import fk_camera, look_angles
    from jev_servo.mission import _retract_choices, choices_to_q_star
    import numpy as np

    poses = [
        [2.65, 0.30, 2.40, 3.80],
        [1.52, 0.14, 2.40, 4.40],
        [0.50, 0.80, 2.50, 3.20],  # near zenith: bare −j1 would look UP
        [2.00, 1.20, 1.80, 2.80],
    ]
    for q in poses:
        T0 = fk_camera(q)
        p0 = T0[:3, 3]
        z0 = T0[:3, 2] / np.linalg.norm(T0[:3, 2])
        el0 = look_angles(T0)[1]
        ch = _retract_choices(q)
        assert any(ch[n] != "stay" for n in ("j1", "j2", "j3")), q
        q1 = choices_to_q_star(q, ch)
        T1 = fk_camera(q1)
        back = float(np.dot(T1[:3, 3] - p0, -z0))
        el1 = look_angles(T1)[1]
        assert back > 4.0, f"q={q} expected retreat, got {back:.1f}mm ch={ch}"
        assert el1 <= el0 + np.radians(1.5), (
            f"q={q} must not look up; Δel={np.degrees(el1 - el0):+.1f}° ch={ch}"
        )
        assert abs(el1 - el0) <= np.radians(3.5), (
            f"q={q} pitch dump; Δel={np.degrees(el1 - el0):+.1f}° ch={ch}"
        )


def test_retract_when_j2_pegged_not_bare_j1_dive():
    """Live tick 133: j2≈qmax, bare −j1 drove face to v=0.78 then lost lock."""
    from jev_servo.fk import fk_camera, look_angles
    from jev_servo.mission import _retract_choices, choices_to_q_star
    import numpy as np

    q = [1.971, 0.10, 2.465, 4.126]
    ch = _retract_choices(q)
    assert ch["j1"] == "toward_neg_s"
    assert ch["j2"] == "toward_pos_s" or ch["j3"] != "stay"
    q1 = choices_to_q_star(q, ch)
    d_el = np.degrees(look_angles(fk_camera(q1))[1] - look_angles(fk_camera(q))[1])
    assert abs(d_el) <= 3.5, f"Δel={d_el:+.1f} ch={ch}"


def test_follow_skips_pitch_while_too_close():
    """Off-center in v must not raise head while span still says too close."""
    from jev_servo.presence import Presence
    from jev_servo.fk import fk_camera, look_angles
    from jev_servo.mission import choices_to_q_star
    import numpy as np

    q = [2.65, 0.30, 2.40, 3.80]
    # Face high in frame + still close → retract, not pitch-up.
    p = Presence(present=True, u=0.50, v=0.20, span=0.35)
    ch = follow_choices(p, q)
    assert ch["j3"] != "toward_neg_s"  # pitch-up wrist
    q1 = choices_to_q_star(q, ch)
    el0 = look_angles(fk_camera(q))[1]
    el1 = look_angles(fk_camera(q1))[1]
    assert el1 <= el0 + np.radians(1.5)


def test_follow_yaw_still_wins_when_off_center_not_stuck():
    from jev_servo.presence import Presence

    q = [2.65, 0.30, 2.30, 3.90]
    p = Presence(present=True, u=0.80, v=0.50, span=0.30)
    ch = follow_choices(p, q)
    assert ch["j0"] == "toward_neg_s"


def test_mission_reacquires_locally_after_miss():
    m = MissionController(miss_limit=2)
    q = [1.52, 0.14, 2.4, 4.4]
    from jev_servo.presence import Presence

    m.step(Presence(present=True, u=0.07, v=0.41, span=0.37), q)
    assert m.mode == "follow"
    assert m.last_j0 == pytest.approx(1.52)
    assert m.step(Presence(present=False), q)["choices"]["j0"].startswith("toward_pos")
    s = m.step(Presence(present=False), [1.40, 0.14, 2.4, 4.4])
    assert s["mode"] == "reacquire"
    assert s["reacq"]["center"] == pytest.approx(1.52)
    for _ in range(4):
        q0 = s["q_star"][0]
        assert abs(q0 - 1.52) <= m.reacq_amp + 0.08
        assert "toward_pos_l" not in s["choices"]["j0"] and "toward_neg_l" not in s["choices"]["j0"]
        s = m.step(Presence(present=False), s["q_star"])
        assert s["mode"] == "reacquire"


def test_mission_switches_to_follow_and_back():
    m = MissionController(miss_limit=2)
    q = [0.0, 0.25, 1.85, 3.55]
    from jev_servo.presence import Presence

    s1 = m.step(Presence(present=False), q)
    assert s1["mode"] == "traverse"

    s2 = m.step(Presence(present=True, u=0.5, v=0.5), q)
    assert s2["mode"] == "follow"

    m.step(Presence(present=False), q)
    s4 = m.step(Presence(present=False), q)
    assert s4["mode"] == "reacquire"
    assert s4["miss_streak"] >= 2


def test_presence_parses_span():
    p = presence_from_scene("face#1@0.10,0.37 span=0.40 left-mid s=0.90")
    assert p.present and abs(p.span - 0.40) < 1e-6
    assert p.face_id == 1


def test_presence_loop_dry_run():
    from jev_servo.loop import run_loop

    ticks = run_loop(
        op="find_any",
        ticks=2,
        dry_run=True,
        mode="presence",
        scene_override="objects:none",
        log_dir=None,
        identify=False,
    )
    assert len(ticks) == 2
    assert ticks[0].search and ticks[0].search["mission"] == "traverse"
    assert ticks[0].moved

    ticks2 = run_loop(
        op="find_any",
        ticks=1,
        dry_run=True,
        mode="presence",
        scene_override="face#2@0.70,0.55 span=0.15",
        log_dir=None,
        identify=False,
    )
    assert ticks2[0].search["mission"] == "follow"
    assert ticks2[0].choices["j0"].startswith("toward_neg")  # tip map: u>0.5 → −j0


def test_find_id_ignores_other_faces():
    from jev_servo.loop import run_loop

    ticks = run_loop(
        op="find_id",
        face_id=9,
        ticks=1,
        dry_run=True,
        mode="presence",
        scene_override="face#2@0.70,0.55 span=0.15",
        log_dir=None,
        identify=False,
    )
    # wrong id → still traverse
    assert ticks[0].search["mission"] == "traverse"


def test_follow_op_does_not_sweep():
    from jev_servo.loop import run_loop

    ticks = run_loop(
        op="follow",
        ticks=1,
        dry_run=True,
        mode="presence",
        scene_override="objects:none",
        log_dir=None,
        identify=False,
    )
    assert ticks[0].moved is False
    assert all(v == "stay" for v in ticks[0].choices.values())
