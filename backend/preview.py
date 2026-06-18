"""Trajectory dry-run: simulate a planned motion before it touches hardware.

Samples a Trajectory the same way the player would (at SENSOR_HZ) and reports
what the safety layers *would* do to it — which joints would be clamped to a
soft limit, and where the commanded speed exceeds max_velocity (the HAL
rate-limits it, so the real move will lag the ideal trajectory). Pure: no HAL,
no state machine, no side effects."""

from __future__ import annotations

import math

from .hardware.base import JointSpec
from .kinematics import PlanarChain
from .trajectory import Trajectory
from .zones import SafetyZone


def simulate_trajectory(
    traj: Trajectory,
    joints: dict[str, JointSpec],
    *,
    hz: float,
    chain: PlanarChain | None = None,
    zone: SafetyZone | None = None,
) -> dict:
    """Return a preview dict: per-joint range + clamp/rate-limit flags, a list
    of human-readable violations, an `ok` flag (true when nothing would be
    clamped), and the end-effector path when a chain is supplied."""
    period = 1.0 / hz
    n = max(2, math.ceil(traj.duration * hz) + 1)
    times = [min(traj.duration, i * period) for i in range(n)]
    times[-1] = traj.duration  # land the last sample exactly on the end

    per_joint: dict[str, dict] = {}
    prev: tuple[float, dict[str, float]] | None = None
    for t in times:
        targets = traj.sample(t)
        for name, val in targets.items():
            spec = joints.get(name)
            d = per_joint.setdefault(
                name,
                {"min": val, "max": val, "clamped": False,
                 "peak_velocity": 0.0, "velocity_limited": False},
            )
            d["min"] = min(d["min"], val)
            d["max"] = max(d["max"], val)
            if spec is not None and (
                val < spec.lower_limit - 1e-9 or val > spec.upper_limit + 1e-9
            ):
                d["clamped"] = True
        if prev is not None:
            dt = t - prev[0]
            if dt > 0:
                for name, val in targets.items():
                    pv = prev[1].get(name)
                    if pv is None:
                        continue
                    v = abs(val - pv) / dt
                    d = per_joint[name]
                    d["peak_velocity"] = max(d["peak_velocity"], v)
                    spec = joints.get(name)
                    if spec is not None and spec.max_velocity > 0 and v > spec.max_velocity + 1e-9:
                        d["velocity_limited"] = True
        prev = (t, targets)

    violations: list[dict] = []
    for name, d in per_joint.items():
        if d["clamped"]:
            violations.append({
                "joint": name,
                "kind": "limit",
                "detail": f"target range [{d['min']:.3f}, {d['max']:.3f}] exceeds joint soft limit",
            })
        if d["velocity_limited"]:
            violations.append({
                "joint": name,
                "kind": "velocity",
                "detail": f"peak {d['peak_velocity']:.2f} rad/s over max_velocity — will be rate-limited",
            })

    result: dict = {
        "duration": traj.duration,
        "samples": len(times),
        "joints": per_joint,
        "violations": violations,
        # A limit clamp alters the commanded pose; a velocity cap only slows
        # it. So `ok` means "no pose will be silently clamped".
        "ok": not any(v["kind"] == "limit" for v in violations),
    }
    if chain is not None:
        sx, sy = chain.forward(traj.sample(0.0))
        ex, ey = chain.forward(traj.sample(traj.duration))
        result["path"] = {"start": [sx, sy], "end": [ex, ey]}
        if zone is not None:
            # Sample the tip along the whole path — a min-jerk move can bow
            # outside a wall even when both endpoints are safe.
            wall: str | None = None
            for t in times:
                tx, ty = chain.forward(traj.sample(t))
                wall = zone.violation(tx, ty)
                if wall:
                    break
            if wall:
                violations.append({"joint": "", "kind": "wall", "detail": wall})
                result["ok"] = False
    return result


def trajectory_zone_violation(
    traj: Trajectory,
    chain: PlanarChain,
    zone: SafetyZone,
    *,
    hz: float,
) -> str | None:
    """First Cartesian safety-zone violation along the tip path, or None.

    Used to block execution: a motion whose end-effector would cross a virtual
    wall is rejected before it runs."""
    period = 1.0 / hz
    n = max(2, math.ceil(traj.duration * hz) + 1)
    for i in range(n):
        t = min(traj.duration, i * period)
        x, y = chain.forward(traj.sample(t))
        reason = zone.violation(x, y)
        if reason:
            return reason
    return None
