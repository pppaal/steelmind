"""Software-only RobotHardware implementation. Used by the simulator and
by tests so the rest of the codebase doesn't need to know whether a real
robot is connected.

Behavior:
- write(targets) sets per-joint target positions (clamped to limits).
- read() advances internal positions toward targets via slew_toward(),
  respecting JointSpec.max_velocity. Computes an IMU reading derived from
  the joints that affect body pose, plus tiny random walk on battery.
- estop() latches; further write() calls become no-ops until clear_estop().
"""

from __future__ import annotations

import asyncio
import math
import random
import time

from ..safety import clamp_targets, slew_toward
from .base import (
    HardwareSnapshot,
    IMUReading,
    JointSpec,
    JointState,
    RobotHardware,
)

# Maps the simulated tracking error (|target - position|, radians) to an
# effort reading. A real servo's load rises while it's fighting to reach a
# far/blocked target; modelling effort as proportional to that error lets the
# overload-protection path be exercised without real hardware.
_EFFORT_GAIN = 8.0


class MockHardware(RobotHardware):
    def __init__(self, joints: list[JointSpec]) -> None:
        self._joints = joints
        self._joints_by_name = {j.name: j for j in joints}
        self._positions: dict[str, float] = {j.name: 0.0 for j in joints}
        self._targets: dict[str, float] = {j.name: 0.0 for j in joints}
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
        # Nothing to open; reset clock so the first read() doesn't fast-forward.
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
            # Targets pinned to current positions so the moment estop clears,
            # the motors don't lurch toward a stale goal.
            self._targets = dict(self._positions)

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
            if who:
                self._warnings = tuple(f"clamped: {n}" for n in who)
            else:
                self._warnings = ()
            self._targets.update(clamped)

    async def read(self) -> HardwareSnapshot:
        async with self._lock:
            now = time.monotonic()
            dt = max(1e-6, min(0.5, now - self._last_read))
            self._last_read = now
            previous = dict(self._positions)
            if self._enabled and not self._estopped:
                self._positions = slew_toward(
                    self._positions, self._targets, self._joints_by_name, dt
                )
            # else: positions hold (real motors brake / freewheel; for the
            # simulator we just freeze).
            self._battery_pct = max(0.0, self._battery_pct - 0.0001)

            joints_state = {
                name: JointState(
                    name=name,
                    position=pos,
                    velocity=(pos - previous.get(name, pos)) / dt,
                    # Effort ~ how hard the servo is still pulling toward its
                    # target. Zero at rest; spikes during a large/blocked move.
                    effort=(
                        _EFFORT_GAIN * abs(self._targets.get(name, pos) - pos)
                        if self._enabled and not self._estopped
                        else 0.0
                    ),
                )
                for name, pos in self._positions.items()
            }
            imu = self._derive_imu(joints_state)
            return HardwareSnapshot(
                timestamp_monotonic=now,
                joints=joints_state,
                imu=imu,
                battery_voltage=24.0 + random.uniform(-0.1, 0.1),
                battery_percent=self._battery_pct,
                enabled=self._enabled,
                estopped=self._estopped,
                warnings=self._warnings,
            )

    @staticmethod
    def _derive_imu(joints: dict[str, JointState]) -> IMUReading:
        """Approximate body tilt from waist + a small share of leg motion.

        Not physically correct — for a real robot, IMU comes from the chip,
        not derived. This just keeps the simulator's IMU feed coupled to the
        joint motion so the 3D scene's body tilt looks sensible."""
        waist = joints.get("waist_yaw")
        hip_l = joints.get("hip_left")
        hip_r = joints.get("hip_right")
        tilt_x = 0.0
        tilt_y = 0.0
        if hip_l and hip_r:
            tilt_x = 0.1 * (hip_l.position - hip_r.position) / 2
        if waist:
            tilt_y = 0.3 * waist.position
        gz = 9.81 + random.uniform(-0.05, 0.05)
        return IMUReading(
            orientation=(tilt_x, tilt_y, 0.0),
            angular_velocity=(tilt_x * math.cos(time.monotonic()), tilt_y, 0.0),
            linear_acceleration=(0.0, 0.0, gz),
        )
