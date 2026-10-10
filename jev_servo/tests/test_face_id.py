"""Face gallery + presence id parsing tests (no camera required)."""

from __future__ import annotations

import numpy as np

from jev_servo.presence import presence_from_scene
from vision.format import format_state
from vision.identity.gallery import FaceGallery
from vision.schema import EmptyRegion, SceneObject


def test_gallery_enroll_match_persist(tmp_path):
    gal = FaceGallery(tmp_path, auto_save=True, match_thresh=0.5)
    emb_a = np.zeros(8)
    emb_a[0] = 1.0
    emb_b = np.zeros(8)
    emb_b[1] = 1.0

    r1, score, is_new = gal.identify_or_enroll(emb_a, name="")
    assert is_new and r1.face_id == 1
    r2, score2, is_new2 = gal.identify_or_enroll(emb_a)
    assert not is_new2 and r2.face_id == 1 and score2 > 0.99
    r3, _, is_new3 = gal.identify_or_enroll(emb_b)
    assert is_new3 and r3.face_id == 2

    gal2 = FaceGallery(tmp_path, auto_save=False)
    assert len(gal2.records) == 2
    fid, s = gal2.match(emb_a)
    assert fid == 1 and s > 0.99

    gal2.rename(1, "shinji")
    assert gal2.records[1].name == "shinji"


def test_format_face_id():
    objs = [
        SceneObject(kind="face", u=0.5, v=0.4, span=0.2, face_id=3, name="aki", score=0.9)
    ]
    state = format_state(objs, [])
    assert "face#3(aki)@0.50,0.40" in state


def test_presence_parses_face_id():
    p = presence_from_scene("face#7(bob)@0.55,0.42 span=0.2 center-mid s=0.9")
    assert p.present and p.face_id == 7 and p.name == "bob"
    assert abs(p.u - 0.55) < 1e-6

    p2 = presence_from_scene("face@0.50,0.50 span=0.2")
    assert p2.present and p2.face_id is None
