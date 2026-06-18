"""Cartesian safety zones ("virtual walls") for the planar end-effector.

A SafetyZone constrains where the tip may travel: an axis-aligned allowed
box, a minimum distance from the base (a crude self-collision / body keep-out),
and any number of rectangular keep-out regions. It's a pure geometric guard —
the trajectory player and dry-run sample the tip path and reject/flag any
sample that leaves the safe region. Inert (None) unless a config declares one,
so it ships off by default."""

from __future__ import annotations

import math
from dataclasses import dataclass

# (x0, y0, x1, y1) axis-aligned rectangle, normalized so x0<=x1, y0<=y1.
KeepOut = tuple[float, float, float, float]


@dataclass(frozen=True)
class SafetyZone:
    min_x: float | None = None
    max_x: float | None = None
    min_y: float | None = None
    max_y: float | None = None
    # Tip must stay at least this far from the base (self-collision proxy).
    min_radius: float | None = None
    # Rectangles the tip must avoid.
    keepout: tuple[KeepOut, ...] = ()
    base_x: float = 0.0
    base_y: float = 0.0

    def violation(self, x: float, y: float) -> str | None:
        """Return a human-readable reason the point (x, y) is unsafe, or None."""
        if self.min_x is not None and x < self.min_x:
            return f"x {x:.3f} below min_x {self.min_x:.3f}"
        if self.max_x is not None and x > self.max_x:
            return f"x {x:.3f} above max_x {self.max_x:.3f}"
        if self.min_y is not None and y < self.min_y:
            return f"y {y:.3f} below min_y {self.min_y:.3f}"
        if self.max_y is not None and y > self.max_y:
            return f"y {y:.3f} above max_y {self.max_y:.3f}"
        if self.min_radius is not None:
            d = math.hypot(x - self.base_x, y - self.base_y)
            if d < self.min_radius:
                return f"within keep-out radius {self.min_radius:.3f} of base (d={d:.3f})"
        for x0, y0, x1, y1 in self.keepout:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return f"inside keep-out box ({x0:.2f},{y0:.2f})-({x1:.2f},{y1:.2f})"
        return None

    def as_dict(self) -> dict:
        return {
            "min_x": self.min_x,
            "max_x": self.max_x,
            "min_y": self.min_y,
            "max_y": self.max_y,
            "min_radius": self.min_radius,
            "keepout": [list(k) for k in self.keepout],
            "base": [self.base_x, self.base_y],
        }


def zone_from_config(data: dict) -> SafetyZone | None:
    """Parse an optional `safety_zone` block from a robot config dict.

    Schema:
      safety_zone:
        min_x: -0.30        # any of the four bounds optional
        max_x:  0.30
        min_y:  0.00        # e.g. a floor the tip can't go below
        max_y:  0.40
        min_radius: 0.05    # optional self-collision keep-out around the base
        keepout:            # optional list of [x0, y0, x1, y1] rectangles
          - [-0.05, -0.05, 0.05, 0.05]
    The base defaults to the chain base when present.
    """
    zone = data.get("safety_zone")
    if not zone:
        return None
    base = data.get("chain", {}).get("base", [0.0, 0.0])
    keepout: list[KeepOut] = []
    for rect in zone.get("keepout", []):
        x0, y0, x1, y1 = (float(v) for v in rect)
        keepout.append((min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))

    def _opt(key: str) -> float | None:
        v = zone.get(key)
        return None if v is None else float(v)

    return SafetyZone(
        min_x=_opt("min_x"),
        max_x=_opt("max_x"),
        min_y=_opt("min_y"),
        max_y=_opt("max_y"),
        min_radius=_opt("min_radius"),
        keepout=tuple(keepout),
        base_x=float(base[0]),
        base_y=float(base[1]),
    )
