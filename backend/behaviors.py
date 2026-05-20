"""Behavior definitions.

A Behavior is a name + a Trajectory factory. The orchestrator plays the
trajectory through the HAL while the state machine reports EXECUTING; the
old "asyncio.sleep + flip state" pattern is gone — every behavior now
actually moves joints.

Trajectories are written against logical joint names (shoulder_left,
hip_right, ...). If a joint is missing from the active robot config, the
HAL silently drops it, so the same behavior file works for sim_humanoid,
torso_humanoid, and so100_arm — each just ignores joints it doesn't have.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from .trajectory import Trajectory, compose, hold, min_jerk, sinusoid


@dataclass
class Behavior:
    name: str
    description: str
    duration: float
    factory: Callable[[], Trajectory]

    def build(self) -> Trajectory:
        return self.factory()


# --- atomic poses (rest poses for the upper body) -----------------------------

_REST = {
    # Sim humanoid joints
    "hip_left": 0.0,
    "hip_right": 0.0,
    "knee_left": 0.0,
    "knee_right": 0.0,
    "shoulder_left": 0.0,
    "shoulder_right": 0.0,
    # Torso humanoid joints
    "waist_yaw": 0.0,
    "head_yaw": 0.0,
    "head_pitch": 0.0,
    "upperarm_left": 0.0,
    "upperarm_right": 0.0,
    "elbow_left": 0.0,
    "elbow_right": 0.0,
    "wrist_left": 0.0,
    "wrist_right": 0.0,
}


def _demo() -> Trajectory:
    # Tiny head nod so /ws viewers see motion even if the robot has no arms.
    return compose(
        min_jerk(_REST, {**_REST, "head_pitch": 0.3}, duration=0.6),
        min_jerk({**_REST, "head_pitch": 0.3}, _REST, duration=0.6),
        hold(_REST, duration=0.3),
    )


def _wave() -> Trajectory:
    # Lift right shoulder, then oscillate wrist while held up; lower back.
    raised = {**_REST, "shoulder_right": -1.4, "upperarm_right": 0.6, "elbow_right": 1.2}
    lift = min_jerk(_REST, raised, duration=0.8)
    wave_motion = sinusoid(
        base=raised,
        amplitudes={"wrist_right": 0.6, "shoulder_right": 0.15},
        frequency_hz=2.0,
        duration=1.8,
    )
    lower = min_jerk(raised, _REST, duration=0.8)
    return compose(lift, wave_motion, lower)


def _squat() -> Trajectory:
    bottom = {**_REST, "hip_left": 0.6, "hip_right": 0.6, "knee_left": -1.2, "knee_right": -1.2}
    down = min_jerk(_REST, bottom, duration=1.2)
    up = min_jerk(bottom, _REST, duration=1.2)
    return compose(down, hold(bottom, duration=0.6), up)


def _patrol() -> Trajectory:
    """In-place march. Alternating leg/arm swing for 5s."""
    swing_amp = 0.45
    arm_amp = 0.4
    return sinusoid(
        base=_REST,
        amplitudes={
            "hip_left": swing_amp,
            "hip_right": -swing_amp,
            "knee_left": -swing_amp * 0.6,
            "knee_right": swing_amp * 0.6,
            "shoulder_left": -arm_amp,
            "shoulder_right": arm_amp,
        },
        frequency_hz=1.5,
        duration=5.0,
        phase_offsets={"knee_left": math.pi / 2, "knee_right": -math.pi / 2},
    )


def _dance() -> Trajectory:
    """Coordinated arm-up + waist-rotate combo."""
    return sinusoid(
        base=_REST,
        amplitudes={
            "shoulder_left": -0.9,
            "shoulder_right": -0.9,
            "upperarm_left": 0.4,
            "upperarm_right": -0.4,
            "waist_yaw": 0.3,
            "hip_left": 0.2,
            "hip_right": -0.2,
        },
        frequency_hz=1.2,
        duration=5.0,
        phase_offsets={"shoulder_right": math.pi, "upperarm_right": math.pi},
    )


BEHAVIORS: dict[str, Behavior] = {
    b.name: b
    for b in [
        Behavior("demo", "Tiny head nod + return.", 1.5, _demo),
        Behavior("wave", "Raise right arm, wave wrist, lower.", 3.4, _wave),
        Behavior("squat", "Bend hips & knees down then up.", 3.0, _squat),
        Behavior("patrol", "In-place alternating march. 5 s.", 5.0, _patrol),
        Behavior("dance", "Arms-up rocking waist + leg motion. 5 s.", 5.0, _dance),
    ]
}


BEHAVIOR_DESCRIPTIONS: dict[str, str] = {n: b.description for n, b in BEHAVIORS.items()}
