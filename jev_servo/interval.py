"""Map discrete JEV choices → safe angle intervals + waypoints."""

from __future__ import annotations

from dataclasses import dataclass

from .mech import CHOICES, JointSpec


@dataclass(frozen=True)
class Interval:
    lo: float
    hi: float

    @property
    def mid(self) -> float:
        return 0.5 * (self.lo + self.hi)

    @property
    def width(self) -> float:
        return self.hi - self.lo

    def contains(self, q: float, *, slack: float = 0.0) -> bool:
        return (self.lo - slack) <= q <= (self.hi + slack)

    def clamp_point(self, q: float) -> float:
        return min(self.hi, max(self.lo, q))


def _clip_interval(lo: float, hi: float, j: JointSpec, q: float) -> Interval:
    """Clip a choice interval to joint limits without freezing directed steps."""
    if hi < lo:
        lo, hi = hi, lo
    w_min = max(j.eps * 2, 1e-3)
    # Intended direction before clipping (used if the window collapses past a rail).
    raw_mid = 0.5 * (lo + hi)
    going_pos = raw_mid >= q

    lo = max(j.qmin, lo)
    hi = min(j.qmax, hi)

    if hi <= lo + 1e-9:
        # Step would land past the rail — park at the rail with a tiny window.
        mid = j.qmax if going_pos else j.qmin
        half = w_min / 2
        lo = max(j.qmin, mid - half)
        hi = min(j.qmax, mid + half)
        if hi <= lo + 1e-9:
            # Exactly at hard stop: degenerate stay at limit.
            lo = hi = mid

    # Cap how far the midpoint may jump this tick.
    mid = 0.5 * (lo + hi) if hi > lo else lo
    if abs(mid - q) > j.dmax:
        sign = 1.0 if mid >= q else -1.0
        mid = q + sign * j.dmax
        half = max((hi - lo) / 2 if hi > lo else j.eps, j.eps)
        lo, hi = mid - half, mid + half
        lo = max(j.qmin, lo)
        hi = min(j.qmax, hi)
        if hi < lo:
            lo, hi = mid, mid
    return Interval(lo=float(lo), hi=float(hi))


def choice_to_interval(choice: str | None, q: float, joint: JointSpec) -> Interval:
    """Convert a JEV choice into a safe [lo, hi] relative to current q."""
    c = choice if choice in CHOICES else "stay"
    if c == "stay":
        lo, hi = q - joint.eps, q + joint.eps
    elif c == "widen_stay":
        lo, hi = q - joint.widen_eps, q + joint.widen_eps
    elif c == "toward_neg_s":
        mid = q - joint.delta_s
        lo, hi = mid - joint.w, mid + joint.w
    elif c == "toward_pos_s":
        mid = q + joint.delta_s
        lo, hi = mid - joint.w, mid + joint.w
    elif c == "toward_neg_l":
        mid = q - joint.delta_l
        lo, hi = mid - joint.w, mid + joint.w
    elif c == "toward_pos_l":
        mid = q + joint.delta_l
        lo, hi = mid - joint.w, mid + joint.w
    else:
        lo, hi = q - joint.eps, q + joint.eps
    return _clip_interval(lo, hi, joint, q)


def waypoint_from_interval(interval: Interval, q: float) -> float:
    """If q already acceptable, hold; else drive toward midpoint."""
    if interval.contains(q):
        return float(q)
    return float(interval.mid)
