"""LeRobot SO-100 adapter. Activated by ROBOT_HARDWARE=lerobot.

LeRobot (Hugging Face) ships its own driver for the SO-100 arm — we wrap
it rather than re-implement the protocol so users benefit from upstream
firmware/calibration fixes.

Install: pip install lerobot
Hardware: SO-100 kit + USB-to-TTL adapter
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from ..safety import clamp_targets
from .base import (
    HardwareError,
    HardwareSnapshot,
    IMUReading,
    JointSpec,
    JointState,
    RobotHardware,
)


class LeRobotHardware(RobotHardware):
    def __init__(self, joints: list[JointSpec], port: str = "/dev/ttyUSB0") -> None:
        self._joints = joints
        self._joints_by_name = {j.name: j for j in joints}
        self.port = port
        self._arm: Any = None
        self._enabled = False
        self._estopped = False
        self._lock = asyncio.Lock()
        self._warnings: tuple[str, ...] = ()

    @property
    def joints(self) -> list[JointSpec]:
        return list(self._joints)

    async def init(self) -> None:
        if self._arm is not None:
            return
        try:
            # LeRobot's robot interface evolves quickly — pin the version in
            # production and adjust this import path if upstream changes it.
            from lerobot.common.robot_devices.motors.feetech import (  # type: ignore[import-untyped]
                FeetechMotorsBus,
            )
        except ImportError as e:
            raise HardwareError(
                "lerobot not installed. Run: pip install lerobot"
            ) from e

        motors = {
            spec.name: (int(spec.hardware_id), "sts3215")  # SO-100 ships sts3215.
            for spec in self._joints
        }
        self._arm = FeetechMotorsBus(port=self.port, motors=motors)
        await asyncio.to_thread(self._arm.connect)

    async def close(self) -> None:
        await self.disable()
        if self._arm is not None:
            await asyncio.to_thread(self._arm.disconnect)
            self._arm = None

    async def enable(self) -> None:
        async with self._lock:
            if self._estopped:
                self._warnings = ("enable refused: estop latched",)
                return
            # LeRobot bus enables torque on connect; explicit flip for clarity.
            await asyncio.to_thread(
                self._arm.write, "Torque_Enable", 1, list(self._joints_by_name)
            )
            self._enabled = True
            self._warnings = ()

    async def disable(self) -> None:
        async with self._lock:
            if self._arm is not None:
                await asyncio.to_thread(
                    self._arm.write, "Torque_Enable", 0, list(self._joints_by_name)
                )
            self._enabled = False

    async def estop(self) -> None:
        async with self._lock:
            if self._arm is not None:
                await asyncio.to_thread(
                    self._arm.write, "Torque_Enable", 0, list(self._joints_by_name)
                )
            self._enabled = False
            self._estopped = True

    async def clear_estop(self) -> None:
        async with self._lock:
            self._estopped = False
            self._warnings = ()

    async def write(self, targets: dict[str, float]) -> None:
        async with self._lock:
            if self._estopped or not self._enabled:
                return
            clamped, who = clamp_targets(targets, self._joints_by_name)
            self._warnings = tuple(f"clamped: {n}" for n in who) if who else ()
            # LeRobot expects per-motor position in its own units (typically
            # degrees for sts3215). Convert and write.
            values_deg = {
                name: (rad * 57.2957795 + self._joints_by_name[name].offset)
                for name, rad in clamped.items()
            }
            await asyncio.to_thread(
                self._arm.write, "Goal_Position", list(values_deg.values()), list(values_deg)
            )

    async def read(self) -> HardwareSnapshot:
        async with self._lock:
            now = time.monotonic()
            if self._arm is None:
                raise HardwareError("read() before init()")
            names = list(self._joints_by_name)
            values_deg = await asyncio.to_thread(self._arm.read, "Present_Position", names)
            joints_state = {
                name: JointState(name=name, position=value / 57.2957795)
                for name, value in zip(names, values_deg, strict=True)
            }
            return HardwareSnapshot(
                timestamp_monotonic=now,
                joints=joints_state,
                imu=IMUReading(),
                enabled=self._enabled,
                estopped=self._estopped,
                warnings=self._warnings,
            )
