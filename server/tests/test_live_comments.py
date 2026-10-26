"""Public livestream comment inbox. Name is required."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from live_comments import CommentBoard, clean_name


def test_name_is_required():
    board = CommentBoard(Path("/tmp/does-not-write-until-post.json"))
    missing = board.post("  ", "你好", "1.1.1.1", now=1)
    assert missing["ok"] is False
    assert "名字" in missing["error"]
    blank = board.post(None, "你好", "1.1.1.1", now=1)
    assert blank["ok"] is False


def test_post_keeps_name_and_rate_limits(tmp_path=None):
    path = Path("/tmp/live-comments-test.json")
    if path.exists():
        path.unlink()
    board = CommentBoard(path)
    ok = board.post(" 小周 ", "挥一下", "1.1.1.1", now=10)
    assert ok == {"ok": True, "seq": 1, "name": "小周", "text": "挥一下"}
    again = board.post("小周", "再来", "1.1.1.1", now=12)
    assert again["ok"] is False
    other = board.post("阿木", "看这边", "2.2.2.2", now=12)
    assert other["ok"] is True
    rows, seq = board.since(1)
    assert seq == 2
    assert rows == [{"seq": 2, "name": "阿木", "text": "看这边", "ts": 12}]
    reloaded = CommentBoard(path)
    assert reloaded.seq == 2
    assert reloaded.since(0)[0][0]["name"] == "小周"
    path.unlink()


def test_clean_name_rejects_long():
    try:
        clean_name("名" * 17)
    except ValueError as exc:
        assert "太长" in str(exc)
    else:
        raise AssertionError("long name should fail")
