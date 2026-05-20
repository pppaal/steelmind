"""Time-parameterized joint trajectory primitives.

A Trajectory is a callable: t (seconds since start) → {joint_name: target_rad}.

The trajectory player in main.py samples it at SENSOR_HZ and pushes the
result through the HAL. The HAL itself enforces velocity limits via slewing,
so the trajectory just has to be smooth-ish; minimum-jerk is provided for
the cases where smoothness genuinely matters."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

Targets = dict[str, float]
TrajectoryFn = Callable[[float], Targets]


@dataclass
class Trajectory:
    """Wrapper carrying the trajectory function + its duration. The state
    machine uses duration to know when to terminate the executing behavior."""

    fn: TrajectoryFn
    duration: float

    def sample(self, t: float) -> Targets:
        return self.fn(min(max(0.0, t), self.duration))


def hold(targets: Targets, duration: float) -> Trajectory:
    """Static pose for `duration` seconds. Useful as the first/last segment
    of a compound behavior."""
    fn: TrajectoryFn = lambda _t: dict(targets)  # noqa: E731 - explicit closure
    return Trajectory(fn=fn, duration=duration)


def linear(start: Targets, end: Targets, duration: float) -> Trajectory:
    """Straight-line interpolation between two joint poses."""
    keys = set(start) | set(end)

    def fn(t: float) -> Targets:
        alpha = 0.0 if duration <= 0 else min(1.0, t / duration)
        return {
            k: (1 - alpha) * start.get(k, 0.0) + alpha * end.get(k, 0.0)
            for k in keys
        }

    return Trajectory(fn=fn, duration=duration)


def min_jerk(start: Targets, end: Targets, duration: float) -> Trajectory:
    """Quintic (minimum-jerk) profile. Position starts and ends with zero
    velocity AND zero acceleration — gentler on the motors than linear and
    much smoother visually."""
    keys = set(start) | set(end)

    def fn(t: float) -> Targets:
        if duration <= 0:
            return dict(end)
        s = min(1.0, t / duration)
        # 10s^3 - 15s^4 + 6s^5 — standard quintic min-jerk profile.
        alpha = 10 * s**3 - 15 * s**4 + 6 * s**5
        return {
            k: (1 - alpha) * start.get(k, 0.0) + alpha * end.get(k, 0.0)
            for k in keys
        }

    return Trajectory(fn=fn, duration=duration)


def sinusoid(
    base: Targets,
    amplitudes: Targets,
    frequency_hz: float,
    duration: float,
    phase_offsets: dict[str, float] | None = None,
) -> Trajectory:
    """Per-joint sine wave around a base pose. Used by wave/dance behaviors.

    target[k](t) = base[k] + amplitudes[k] * sin(2π · freq · t + phase[k])
    """
    keys = set(base) | set(amplitudes)
    phase = phase_offsets or {}
    omega = 2.0 * math.pi * frequency_hz

    def fn(t: float) -> Targets:
        return {
            k: base.get(k, 0.0) + amplitudes.get(k, 0.0) * math.sin(omega * t + phase.get(k, 0.0))
            for k in keys
        }

    return Trajectory(fn=fn, duration=duration)


def compose(*segments: Trajectory) -> Trajectory:
    """Glue multiple trajectories end-to-end. Total duration is the sum;
    sampling dispatches to the segment containing t."""
    total = sum(s.duration for s in segments)

    def fn(t: float) -> Targets:
        accumulated = 0.0
        for seg in segments:
            if t <= accumulated + seg.duration:
                return seg.sample(t - accumulated)
            accumulated += seg.duration
        return segments[-1].sample(segments[-1].duration)

    return Trajectory(fn=fn, duration=total)
