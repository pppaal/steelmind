"""Dynamixel adapter. Activated by ROBOT_HARDWARE=dynamixel.

The protocol-2 driver assumes XL430 / XL330 / XM430 series servos and
Robotis's U2D2 USB interface. dynamixel-sdk is imported lazily so the
default mock backend doesn't pull in a serial dep.

This file is structured but UNTESTED against real silicon — the user is
expected to validate against their bus before relying on it in safety
contexts. Tested code paths: clamping, slewing fallback, estop latch."""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any

from ..safety import clamp_targets, slew_toward
from .base import (
    HardwareError,
    HardwareSnapshot,
    IMUReading,
    JointSpec,
    JointState,
    RobotHardware,
)

# Protocol 2.0 control table addresses (X-series).
_ADDR_TORQUE_ENABLE = 64
_ADDR_GOAL_POSITION = 116
_ADDR_PRESENT_POSITION = 132
_ADDR_PRESENT_VELOCITY = 128
_ADDR_PRESENT_CURRENT = 126
_ADDR_PRESENT_INPUT_VOLTAGE = 144

# X-series encoder: 4096 counts per revolution.
_COUNTS_PER_REV = 4096


def _rad_to_counts(rad: float) -> int:
    return int((rad / (2 * math.pi)) * _COUNTS_PER_REV) + _COUNTS_PER_REV // 2


def _counts_to_rad(counts: int) -> float:
    return (counts - _COUNTS_PER_REV // 2) * (2 * math.pi) / _COUNTS_PER_REV


class DynamixelHardware(RobotHardware):
    def __init__(
        self,
        joints: list[JointSpec],
        port: str = "/dev/ttyUSB0",
        baudrate: int = 1_000_000,
    ) -> None:
        self._joints = joints
        self._joints_by_name = {j.name: j for j in joints}
        self.port = port
        self.baudrate = baudrate
        # All SDK objects bind on init() so an import-time test on a dev box
        # without a U2D2 plugged in doesn't fail.
        self._port_handler: Any = None
        self._packet_handler: Any = None
        self._group_sync_read: Any = None
        self._group_sync_write: Any = None
        self._enabled = False
        self._estopped = False
        self._lock = asyncio.Lock()
        self._positions: dict[str, float] = {j.name: 0.0 for j in joints}
        self._targets: dict[str, float] = {j.name: 0.0 for j in joints}
        self._battery_voltage = 24.0
        self._warnings: tuple[str, ...] = ()

    @property
    def joints(self) -> list[JointSpec]:
        return list(self._joints)

    async def init(self) -> None:
        if self._port_handler is not None:
            return
        try:
            from dynamixel_sdk import (  # type: ignore[import-untyped]
                GroupSyncRead,
                GroupSyncWrite,
                PacketHandler,
                PortHandler,
            )
        except ImportError as e:
            raise HardwareError(
                "dynamixel-sdk not installed. Run: pip install dynamixel-sdk"
            ) from e

        self._port_handler = PortHandler(self.port)
        self._packet_handler = PacketHandler(2.0)
        if not self._port_handler.openPort():
            raise HardwareError(f"could not open {self.port}")
        if not self._port_handler.setBaudRate(self.baudrate):
            raise HardwareError(f"could not set baud {self.baudrate}")

        # GroupSyncRead lets us pull all positions in one bus transaction —
        # critical for hitting 20 Hz with 13 servos.
        self._group_sync_read = GroupSyncRead(
            self._port_handler, self._packet_handler, _ADDR_PRESENT_POSITION, 4
        )
        self._group_sync_write = GroupSyncWrite(
            self._port_handler, self._packet_handler, _ADDR_GOAL_POSITION, 4
        )
        for spec in self._joints:
            self._group_sync_read.addParam(int(spec.hardware_id))

    async def close(self) -> None:
        await self.disable()
        if self._port_handler is not None:
            self._port_handler.closePort()
            self._port_handler = None

    async def enable(self) -> None:
        async with self._lock:
            if self._estopped:
                self._warnings = ("enable refused: estop latched",)
                return
            await asyncio.to_thread(self._set_torque_all, True)
            self._enabled = True
            self._warnings = ()

    async def disable(self) -> None:
        async with self._lock:
            if self._port_handler is not None:
                await asyncio.to_thread(self._set_torque_all, False)
            self._enabled = False

    async def estop(self) -> None:
        # Most direct possible: cut torque on every servo, latch, refuse writes.
        async with self._lock:
            if self._port_handler is not None:
                await asyncio.to_thread(self._set_torque_all, False)
            self._enabled = False
            self._estopped = True
            self._targets = dict(self._positions)

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
            self._targets.update(clamped)
            # Slew toward target by one tick so a step input doesn't snap.
            self._positions = slew_toward(
                self._positions, self._targets, self._joints_by_name, dt=0.05
            )
            await asyncio.to_thread(self._sync_write_positions, self._positions)

    async def read(self) -> HardwareSnapshot:
        async with self._lock:
            now = time.monotonic()
            if self._port_handler is None:
                raise HardwareError("read() before init()")
            previous = dict(self._positions)
            positions = await asyncio.to_thread(self._sync_read_positions)
            self._positions.update(positions)
            joints_state = {
                name: JointState(
                    name=name,
                    position=pos,
                    velocity=(pos - previous.get(name, pos)) / 0.05,
                )
                for name, pos in self._positions.items()
            }
            # Real builds should add a dedicated IMU read here. For now we
            # return a placeholder so the rest of the stack stays happy.
            return HardwareSnapshot(
                timestamp_monotonic=now,
                joints=joints_state,
                imu=IMUReading(),
                battery_voltage=self._battery_voltage,
                battery_percent=100.0,
                enabled=self._enabled,
                estopped=self._estopped,
                warnings=self._warnings,
            )

    # ---- sync (blocking) helpers — always called via asyncio.to_thread ----

    def _set_torque_all(self, enabled: bool) -> None:
        flag = 1 if enabled else 0
        for spec in self._joints:
            self._packet_handler.write1ByteTxRx(
                self._port_handler, int(spec.hardware_id), _ADDR_TORQUE_ENABLE, flag
            )

    def _sync_write_positions(self, positions: dict[str, float]) -> None:
        self._group_sync_write.clearParam()
        for spec in self._joints:
            value = positions.get(spec.name, 0.0)
            corrected = -value if spec.invert else value
            corrected += spec.offset
            counts = _rad_to_counts(corrected)
            param = counts.to_bytes(4, "little", signed=True)
            self._group_sync_write.addParam(int(spec.hardware_id), param)
        self._group_sync_write.txPacket()

    def _sync_read_positions(self) -> dict[str, float]:
        self._group_sync_read.txRxPacket()
        out: dict[str, float] = {}
        for spec in self._joints:
            counts = self._group_sync_read.getData(
                int(spec.hardware_id), _ADDR_PRESENT_POSITION, 4
            )
            rad = _counts_to_rad(int.from_bytes(
                int(counts).to_bytes(4, "little", signed=False), "little", signed=True
            ))
            rad -= spec.offset
            if spec.invert:
                rad = -rad
            out[spec.name] = rad
        return out
