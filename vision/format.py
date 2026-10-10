from __future__ import annotations

from .schema import EmptyRegion, SceneObject


def format_state(objects: list[SceneObject], empties: list[EmptyRegion], *, max_obj: int = 8, max_empty: int = 6) -> str:
    """One-line state for text judges (JEV / Agent). No prose."""
    parts: list[str] = []
    for o in objects[:max_obj]:
        if o.kind == "face" and o.face_id is not None:
            tag = f"face#{o.face_id}"
            if o.name:
                tag = f"{tag}({o.name})"
        else:
            tag = o.kind
        parts.append(
            f"{tag}@{o.u:.2f},{o.v:.2f} span={o.span:.2f} {o.where} s={o.score:.2f}"
        )
    if not objects:
        parts.append("objects:none")
    for e in empties[:max_empty]:
        parts.append(f"empty@{e.where} area={e.area:.2f}")
    if not empties:
        parts.append("empty:none")
    return "; ".join(parts)
