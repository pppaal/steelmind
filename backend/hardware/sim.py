"""Physics-ish RobotHardware: a second-order joint model with gravity.

Unlike MockHardware (which kinematically slews toward the target), each joint
here is a small dynamical system — a PD "motor" driving an inertia against a
gravity load and hard joint limits. That makes the rest of the stack behave
realistically *without real hardware*:

- holding a joint away from its hanging pose costs steady effort (the motor
  fights gravity), so the load telemetry and overload protection mean
  something;
- a blocked / far target spikes effort, tripping the overload reflex;
- there is a little steady-state sag, as a real position servo has.

Still dependency-free (stdlib math). Selected with ROBOT_HARDWARE=sim. The
gravity model (torque ∝ -sin(angle), i.e. each joint hangs toward 0) is an
approximation, not a URDF-accurate dynamics — enough to exercise the stack.
"""

from __future__ import annotations

import asyncio
import math
import os
import random
import time

from ..safety import clamp_targets
from .base import HardwareSnapshot, JointSpec, JointState, RobotHardware
from .mock import MockHardware

# Defaults chosen to settle quickly without oscillation (roughly critically
# damped for unit inertia). Override per deployment via SIM_* env.
_KP = float(os.getenv("SIM_KP", "40.0"))  # position gain (motor stiffness)
_KD = float(os.getenv("SIM_KD", "12.0"))  # velocity gain (damping)
_INERTIA = float(os.getenv("SIM_INERTIA", "1.0"))
_GRAVITY = float(os.getenv("SIM_GRAVITY", "6.0"))  # gravity torque scale
_SUBSTEP = float(os.getenv("SIM_SUBSTEP_SEC", "0.005"))  # integration step cap


class PhysicsSim(RobotHardware):
    def __init__(
        self,
        joints: list[JointSpec],
        *,
        kp: float = _KP,
        kd: float = _KD,
        inertia: float = _INERTIA,
        gravity: float = _GRAVITY,
        substep: float = _SUBSTEP,
    ) -> None:
        self._joints = joints
        self._joints_by_name = {j.name: j for j in joints}
        self._pos: dict[str, float] = {j.name: 0.0 for j in joints}
        self._vel: dict[str, float] = {j.name: 0.0 for j in joints}
        self._targets: dict[str, float] = {j.name: 0.0 for j in joints}
        self._effort: dict[str, float] = {j.name: 0.0 for j in joints}
        self._kp, self._kd, self._inertia = kp, kd, inertia
        self._gravity, self._substep = gravity, substep
        self._last_read = time.monotonic()
        self._enabled = False
        self._estopped = False
        self._battery_pct = 100.0
        self._lock = asyncio.Lock()
        self._warnings: tuple[str, ...] = ()

    @property
    def joints(self) -> list[JointSpec]:
        return list(self._joints)

    async def init(self) -> None:
        self._last_read = time.monotonic()

    async def close(self) -> None:
        await self.disable()

    async def enable(self) -> None:
        async with self._lock:
            if self._estopped:
                self._warnings = ("enable refused: estop latched",)
                return
            self._enabled = True
            self._warnings = ()

    async def disable(self) -> None:
        async with self._lock:
            self._enabled = False

    async def estop(self) -> None:
        async with self._lock:
            self._estopped = True
            self._enabled = False
            self._targets = dict(self._pos)
            self._vel = {n: 0.0 for n in self._vel}

    async def clear_estop(self) -> None:
        async with self._lock:
            self._estopped = False
            self._warnings = ()

    async def write(self, targets: dict[str, float]) -> None:
        async with self._lock:
            if self._estopped:
                self._warnings = ("write ignored: estop latched",)
                return
            clamped, who = clamp_targets(targets, self._joints_by_name)
            self._warnings = tuple(f"clamped: {n}" for n in who) if who else ()
            self._targets.update(clamped)

    def _integrate(self, dt: float) -> None:
        steps = max(1, math.ceil(dt / self._substep))
        h = dt / steps
        for name, spec in self._joints_by_name.items():
            pos, vel = self._pos[name], self._vel[name]
            target = self._targets.get(name, 0.0)
            torque_cmd = 0.0
            for _ in range(steps):
                torque_cmd = self._kp * (target - pos) - self._kd * vel
                torque_grav = -self._gravity * math.sin(pos)
                acc = (torque_cmd + torque_grav) / self._inertia
                vel += acc * h
                pos += vel * h
                if pos <= spec.lower_limit:
                    pos, vel = spec.lower_limit, 0.0
                elif pos >= spec.upper_limit:
                    pos, vel = spec.upper_limit, 0.0
            self._pos[name], self._vel[name] = pos, vel
            # Effort = how hard the motor is pulling (incl. holding gravity).
            self._effort[name] = abs(torque_cmd)

    async def read(self) -> HardwareSnapshot:
        async with self._lock:
            now = time.monotonic()
            dt = max(1e-6, min(0.5, now - self._last_read))
            self._last_read = now
            if self._enabled and not self._estopped:
                self._integrate(dt)
            else:
                # Brakes engaged: hold pose, no motor effort.
                self._vel = {n: 0.0 for n in self._vel}
                self._effort = {n: 0.0 for n in self._effort}
            self._battery_pct = max(0.0, self._battery_pct - 0.0001)

            joints_state = {
                name: JointState(
                    name=name,
                    position=pos,
                    velocity=self._vel[name],
                    effort=self._effort[name],
                )
                for name, pos in self._pos.items()
            }
            return HardwareSnapshot(
                timestamp_monotonic=now,
                joints=joints_state,
                imu=MockHardware._derive_imu(joints_state),
                battery_voltage=24.0 + random.uniform(-0.1, 0.1),
                battery_percent=self._battery_pct,
                enabled=self._enabled,
                estopped=self._estopped,
                warnings=self._warnings,
            )
