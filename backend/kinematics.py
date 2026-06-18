"""Planar forward/inverse kinematics for a revolute joint chain.

Scope: a single kinematic chain of revolute joints lying in a plane (the
arm's main reach plane). Joint angles are summed along the chain — this is
the textbook planar manipulator model and covers an arm like the SO-100's
shoulder-lift → elbow → wrist subchain.

No numpy: the Jacobian is 2×N and the damped-least-squares step only ever
inverts a 2×2 matrix, which is cheap and dependency-free.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Link:
    joint: str
    length: float  # distance from this joint to the next joint / end effector


@dataclass
class PlanarChain:
    """Ordered base→tip. `base_x/base_y` is where the first joint sits."""

    links: list[Link]
    base_x: float = 0.0
    base_y: float = 0.0

    @property
    def reach(self) -> float:
        """Max distance the tip can be from the base (arm fully extended)."""
        return sum(link.length for link in self.links)

    def forward(self, angles: dict[str, float]) -> tuple[float, float]:
        """Joint angles (rad) → end-effector (x, y). Missing joints = 0."""
        x, y = self.base_x, self.base_y
        theta = 0.0
        for link in self.links:
            theta += angles.get(link.joint, 0.0)
            x += link.length * math.cos(theta)
            y += link.length * math.sin(theta)
        return x, y

    def workspace(
        self,
        limits: dict[str, tuple[float, float]] | None = None,
        *,
        max_samples: int = 20000,
    ) -> dict:
        """Reachable-workspace envelope as an annulus around the base.

        Samples joint space within `limits` (full ±π when unspecified), runs
        forward kinematics, and returns the min/max tip distance from the
        base. `reach` is the theoretical fully-extended span; `outer_radius`
        is what the joint limits actually allow (≤ reach). The grid density
        per joint is chosen so the total sample count stays under
        `max_samples`. The annulus is a fast, necessary pre-check for whether
        a target is reachable — IK (/reach) remains the authority."""
        import itertools

        limits = limits or {}
        n = len(self.links)
        grid = max(2, int(max_samples ** (1.0 / n))) if n else 1
        axes: list[list[float]] = []
        for link in self.links:
            lo, hi = limits.get(link.joint, (-math.pi, math.pi))
            if hi <= lo:
                axes.append([lo])
            else:
                step = (hi - lo) / (grid - 1)
                axes.append([lo + i * step for i in range(grid)])

        inner = math.inf
        outer = 0.0
        for combo in itertools.product(*axes):
            angles = {self.links[i].joint: combo[i] for i in range(n)}
            x, y = self.forward(angles)
            d = math.hypot(x - self.base_x, y - self.base_y)
            inner = min(inner, d)
            outer = max(outer, d)
        if inner is math.inf:
            inner = 0.0
        return {
            "base": [self.base_x, self.base_y],
            "reach": self.reach,
            "inner_radius": inner,
            "outer_radius": outer,
        }

    def jacobian(self, angles: dict[str, float]) -> list[tuple[float, float]]:
        """2×N Jacobian as a list of (dx/dθ_i, dy/dθ_i) columns.

        Joint i rotates every link from i to the tip, so its column is the
        sum over k≥i of the perpendicular of each link vector."""
        # Precompute cumulative angle and absolute position of each link tip.
        thetas: list[float] = []
        theta = 0.0
        for link in self.links:
            theta += angles.get(link.joint, 0.0)
            thetas.append(theta)

        # tip_x[k], tip_y[k]: position after applying links 0..k
        tip_x = [0.0] * len(self.links)
        tip_y = [0.0] * len(self.links)
        x, y = self.base_x, self.base_y
        for k, link in enumerate(self.links):
            x += link.length * math.cos(thetas[k])
            y += link.length * math.sin(thetas[k])
            tip_x[k] = x
            tip_y[k] = y

        end_x, end_y = tip_x[-1], tip_y[-1]
        # Joint i is located at the tip of link i-1 (base for i=0).
        cols: list[tuple[float, float]] = []
        for i in range(len(self.links)):
            jx = self.base_x if i == 0 else tip_x[i - 1]
            jy = self.base_y if i == 0 else tip_y[i - 1]
            # d(end)/dθ_i = ẑ × (end - joint_i) = (-(ey-jy), (ex-jx))
            cols.append((-(end_y - jy), (end_x - jx)))
        return cols

    def _dls_solve(
        self,
        target: tuple[float, float],
        seed: dict[str, float],
        limits: dict[str, tuple[float, float]],
        tolerance: float,
        max_iters: int,
        damping: float,
        step_clamp: float,
    ) -> tuple[dict[str, float], float]:
        """One damped-least-squares descent from a single seed. Returns the
        best pose found and its residual."""
        angles = {link.joint: seed.get(link.joint, 0.0) for link in self.links}
        tx, ty = target
        residual = math.inf
        for _ in range(max_iters):
            ex, ey = self.forward(angles)
            err_x, err_y = tx - ex, ty - ey
            residual = math.hypot(err_x, err_y)
            if residual < tolerance:
                break
            cols = self.jacobian(angles)
            # (J Jᵀ + λ²I) is 2×2: [[a, b], [b, c]] — always invertible thanks
            # to the λ² regularization, so no singularity guard needed.
            a = sum(cx * cx for cx, _ in cols) + damping * damping
            b = sum(cx * cy for cx, cy in cols)
            c = sum(cy * cy for _, cy in cols) + damping * damping
            det = a * c - b * b
            inv_x = (c * err_x - b * err_y) / det
            inv_y = (-b * err_x + a * err_y) / det
            for i, link in enumerate(self.links):
                cx, cy = cols[i]
                dtheta = max(-step_clamp, min(step_clamp, cx * inv_x + cy * inv_y))
                lo, hi = limits.get(link.joint, (-math.pi, math.pi))
                angles[link.joint] = max(lo, min(hi, angles[link.joint] + dtheta))
        return angles, residual

    def inverse(
        self,
        target: tuple[float, float],
        seed: dict[str, float],
        limits: dict[str, tuple[float, float]] | None = None,
        *,
        tolerance: float = 1e-3,
        max_iters: int = 400,
        damping: float = 0.05,
        step_clamp: float = 0.3,
        restarts: int = 12,
    ) -> tuple[dict[str, float], bool, float]:
        """Damped least squares IK with random restarts. Returns (angles,
        reached, residual).

        A single DLS descent can fall into a folded singularity (tip at the
        base) or other local minimum. We try the caller's seed first, then up
        to `restarts` randomized seeds within joint limits, keeping the best
        residual. The RNG is fixed-seeded so results are deterministic across
        runs/tests. If the target is outside the workspace, the best pose is
        the closest reachable one and reached=False."""
        limits = limits or {}
        rng = random.Random(1729)  # deterministic restarts

        best_angles, best_res = self._dls_solve(
            target, seed, limits, tolerance, max_iters, damping, step_clamp
        )
        if best_res < tolerance:
            return best_angles, True, best_res

        for _ in range(restarts):
            rand_seed = {
                link.joint: rng.uniform(*limits.get(link.joint, (-math.pi, math.pi)))
                for link in self.links
            }
            angles, res = self._dls_solve(
                target, rand_seed, limits, tolerance, max_iters, damping, step_clamp
            )
            if res < best_res:
                best_angles, best_res = angles, res
            if best_res < tolerance:
                return best_angles, True, best_res

        return best_angles, best_res < tolerance, best_res


def chain_from_config(data: dict) -> PlanarChain | None:
    """Parse an optional `chain` block from a robot config dict.

    Schema:
      chain:
        base: [0.0, 0.0]          # optional
        links:
          - { joint: shoulder_lift, length: 0.12 }
          - { joint: elbow_flex,    length: 0.12 }
          - { joint: wrist_flex,    length: 0.06 }
    """
    chain = data.get("chain")
    if not chain:
        return None
    base = chain.get("base", [0.0, 0.0])
    links = [Link(joint=str(item["joint"]), length=float(item["length"])) for item in chain["links"]]
    if not links:
        return None
    return PlanarChain(links=links, base_x=float(base[0]), base_y=float(base[1]))
