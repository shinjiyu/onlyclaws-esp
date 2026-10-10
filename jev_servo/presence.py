"""Person presence from tip-camera scene text (YuNet face + optional gallery id)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

# face#3@u,v or face#3(name)@u,v or legacy face@u,v — optional span=
_FACE_RE = re.compile(
    r"(?:^|[;\s])face(?:#(?P<id>\d+)(?:\((?P<name>[^)]*)\))?)?"
    r"@(?P<u>0?\.\d+|1(?:\.0+)?),(?P<v>0?\.\d+|1(?:\.0+)?)"
    r"(?:[^;]*?\bspan=(?P<span>0?\.\d+|1(?:\.0+)?))?",
    re.I,
)


@dataclass(frozen=True)
class Presence:
    """Binary presence + optional image center / gallery id for follow."""

    present: bool
    u: float | None = None
    v: float | None = None
    kind: str = "face"
    face_id: int | None = None
    name: str = ""
    span: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def presence_from_scene(scene: str, *, kind: str = "face") -> Presence:
    """Parse pathway-B state. Prefer face#id; fall back to bare face@."""
    if kind != "face":
        kind = "face"
    m = _FACE_RE.search(scene or "")
    if not m:
        return Presence(present=False, kind=kind)
    fid = int(m.group("id")) if m.group("id") else None
    span = float(m.group("span")) if m.group("span") else None
    return Presence(
        present=True,
        u=float(m.group("u")),
        v=float(m.group("v")),
        kind=kind,
        face_id=fid,
        name=(m.group("name") or "").strip(),
        span=span,
    )
