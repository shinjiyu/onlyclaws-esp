"""Room-search planner: raise look_el, then advance want_az (no left-right dither).

Host-owned state machine. JEV still picks discrete δq via PREDICT residuals
against (want_az, want_el) — but want_az now marches along a sweep, so j0 has
a real yaw target instead of err_az≡0.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


def _wrap_pi(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def _ang_err(want: float, have: float) -> float:
    return _wrap_pi(want - have)


@dataclass
class SearchSnapshot:
    phase: str  # "raise" | "sweep" | "idle"
    want_az: float
    want_el: float
    err_az: float
    err_el: float
    sweep_dir: int
    visited_n: int
    visited_az: list[float] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "want_az": round(self.want_az, 4),
            "want_el": round(self.want_el, 4),
            "err_az": round(self.err_az, 4),
            "err_el": round(self.err_el, 4),
            "sweep_dir": self.sweep_dir,
            "visited_n": self.visited_n,
            "visited_az": [round(a, 3) for a in self.visited_az[-8:]],
        }


@dataclass
class SearchPlanner:
    """Persistent across ticks while TARGET_STATUS=MISSING."""

    phase: str = "raise"
    want_az: float | None = None
    want_el: float | None = None
    sweep_dir: int = 1
    visited_az: list[float] = field(default_factory=list)
    # look-az workspace (approx); clamp waypoints
    az_lo: float = -2.8
    az_hi: float = 2.8
    step_az: float = 0.50  # ~half horizontal FOV → overlap
    el_floor: float = -0.25
    el_ceil: float = 0.55
    el_tol: float = 0.14
    az_tol: float = 0.18
    row_el_bump: float = 0.28

    def reset(self) -> None:
        self.phase = "raise"
        self.want_az = None
        self.want_el = None
        self.sweep_dir = 1
        self.visited_az = []

    def update(self, *, look_az: float, look_el: float, status: str) -> SearchSnapshot:
        if status != "MISSING":
            # Keep memory but idle — resume raise if missing again with fresh wants.
            if status in ("VISIBLE", "CENTERED"):
                self.reset()
            return SearchSnapshot(
                phase="idle",
                want_az=look_az,
                want_el=look_el,
                err_az=0.0,
                err_el=0.0,
                sweep_dir=self.sweep_dir,
                visited_n=len(self.visited_az),
                visited_az=list(self.visited_az),
            )

        if self.want_az is None or self.want_el is None:
            self.phase = "raise"
            self.want_az = look_az
            self.want_el = min(self.el_ceil, max(self.el_floor, look_el + 0.40))

        assert self.want_az is not None and self.want_el is not None

        if self.phase == "raise":
            # Hold yaw target = current az so residual doesn't demand dither.
            self.want_az = look_az
            if look_el >= self.want_el - self.el_tol:
                self.phase = "sweep"
                self.want_az = _wrap_pi(look_az + self.sweep_dir * self.step_az)
                self.want_az = min(self.az_hi, max(self.az_lo, self.want_az))
                if abs(_ang_err(self.want_az, look_az)) < self.az_tol * 0.5:
                    # Hit clamp immediately — reverse.
                    self.sweep_dir *= -1
                    self.want_az = _wrap_pi(look_az + self.sweep_dir * self.step_az)
                    self.want_az = min(self.az_hi, max(self.az_lo, self.want_az))

        elif self.phase == "sweep":
            if abs(_ang_err(self.want_az, look_az)) < self.az_tol:
                self.visited_az.append(float(self.want_az))
                nxt = _wrap_pi(self.want_az + self.sweep_dir * self.step_az)
                if nxt > self.az_hi or nxt < self.az_lo:
                    self.sweep_dir *= -1
                    self.want_el = min(self.el_ceil, self.want_el + self.row_el_bump)
                    nxt = _wrap_pi(look_az + self.sweep_dir * self.step_az)
                    nxt = min(self.az_hi, max(self.az_lo, nxt))
                    # If still need more elevation, briefly re-raise.
                    if look_el < self.want_el - self.el_tol:
                        self.phase = "raise"
                        self.want_az = look_az
                self.want_az = nxt

        err_az = _ang_err(self.want_az, look_az)
        err_el = self.want_el - look_el
        return SearchSnapshot(
            phase=self.phase,
            want_az=float(self.want_az),
            want_el=float(self.want_el),
            err_az=err_az,
            err_el=err_el,
            sweep_dir=self.sweep_dir,
            visited_n=len(self.visited_az),
            visited_az=list(self.visited_az),
        )

    def format_block(self, snap: SearchSnapshot) -> str:
        vis = ",".join(f"{a:.2f}" for a in snap.visited_az[-6:]) or "(none)"
        return (
            f"SEARCH_PLAN phase={snap.phase} sweep_dir={snap.sweep_dir:+d} "
            f"visited_n={snap.visited_n} visited_az=[{vis}]\n"
            f"SEARCH_BEARING want_az={snap.want_az:.4f} want_el={snap.want_el:.4f} "
            f"err_az={snap.err_az:+.4f} err_el={snap.err_el:+.4f}\n"
            f"  raise: drive err_el→0 (j0 may stay). "
            f"sweep: drive err_az→0 with j0 (one direction until waypoint)."
        )
