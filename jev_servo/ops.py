"""Finite presence ops — no free-form natural language goals."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

OpName = Literal["find_any", "find_id", "follow"]

OPS: tuple[OpName, ...] = ("find_any", "find_id", "follow")

_OP_HELP = {
    "find_any": "Traverse until any face, then follow; enroll/id along the way",
    "find_id": "Traverse until face#N, then follow that id only",
    "follow": "Follow face in frame (any, or face#N if target set); no search sweep",
}


@dataclass(frozen=True)
class Op:
    name: OpName
    target_id: int | None = None  # required for find_id; optional filter for follow

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def label(self) -> str:
        if self.name == "find_id":
            return f"find_id#{self.target_id}"
        if self.name == "follow" and self.target_id is not None:
            return f"follow#{self.target_id}"
        return self.name


def parse_op(name: str, target_id: int | None = None) -> Op:
    n = (name or "").strip().lower().replace("-", "_")
    if n not in OPS:
        raise ValueError(f"unknown op {name!r}; choose one of {OPS}")
    if n == "find_id":
        if target_id is None or int(target_id) < 1:
            raise ValueError("find_id requires --face-id / target_id >= 1")
        return Op(name="find_id", target_id=int(target_id))
    tid = int(target_id) if target_id is not None else None
    if tid is not None and tid < 1:
        tid = None
    return Op(name=n, target_id=tid)  # type: ignore[arg-type]


def op_help() -> dict[str, str]:
    return dict(_OP_HELP)
