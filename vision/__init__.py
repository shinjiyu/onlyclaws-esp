"""OnlyClaws vision pathway — host-side frame → objects + empties + compact state.

Not part of ESP firmware / RoArm product. See doc/structurizr/VISION-PATHWAY.md.
"""

from .pipeline import describe_bgr, describe_path
from .schema import EmptyRegion, SceneObject, SceneDesc

__all__ = [
    "SceneDesc",
    "SceneObject",
    "EmptyRegion",
    "describe_bgr",
    "describe_path",
]
