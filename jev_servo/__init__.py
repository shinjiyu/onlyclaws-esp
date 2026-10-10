"""OnlyClaws pathway C — host JEV per-joint safe intervals → one cloud arm goal.

See doc/structurizr/JEV-SERVO-PATHWAY.md. Not ESP firmware.
"""

from .interval import Interval, choice_to_interval, waypoint_from_interval
from .mech import JOINTS, JointSpec
from .tick import DecisionTick, run_tick

__all__ = [
    "JOINTS",
    "JointSpec",
    "Interval",
    "choice_to_interval",
    "waypoint_from_interval",
    "DecisionTick",
    "run_tick",
]
