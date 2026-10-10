from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def quadrant(u: float, v: float) -> str:
    """Map normalized (u,v) to left|center|right - upper|mid|lower."""
    if u < 0.33:
        horiz = "left"
    elif u > 0.67:
        horiz = "right"
    else:
        horiz = "center"
    if v < 0.33:
        vert = "upper"
    elif v > 0.67:
        vert = "lower"
    else:
        vert = "mid"
    return f"{horiz}-{vert}"


@dataclass
class SceneObject:
    kind: str
    u: float  # [0,1] center x
    v: float  # [0,1] center y
    span: float  # max(w,h) / frame width, rough size
    score: float = 1.0
    w: float = 0.0  # normalized box width
    h: float = 0.0  # normalized box height
    face_id: int | None = None  # gallery id when identified
    name: str = ""  # optional human label

    @property
    def where(self) -> str:
        return quadrant(self.u, self.v)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["where"] = self.where
        return d


@dataclass
class EmptyRegion:
    """Free-space blob after object occupancy is masked out."""

    u: float
    v: float
    area: float  # fraction of frame
    w: float = 0.0
    h: float = 0.0

    @property
    def where(self) -> str:
        return quadrant(self.u, self.v)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["where"] = self.where
        return d


@dataclass
class SceneDesc:
    width: int
    height: int
    objects: list[SceneObject] = field(default_factory=list)
    empties: list[EmptyRegion] = field(default_factory=list)
    state: str = ""
    ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "objects": [o.to_dict() for o in self.objects],
            "empties": [e.to_dict() for e in self.empties],
            "state": self.state,
            "ms": self.ms,
        }
