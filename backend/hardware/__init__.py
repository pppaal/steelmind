"""Factory for picking the right RobotHardware implementation at startup."""

from __future__ import annotations

import logging
import os

from .base import (
    HardwareError,
    HardwareSnapshot,
    IMUReading,
    JointSpec,
    JointState,
    RobotHardware,
)
from .mock import MockHardware

logger = logging.getLogger("steelmind.hardware")

__all__ = [
    "HardwareError",
    "HardwareSnapshot",
    "IMUReading",
    "JointSpec",
    "JointState",
    "MockHardware",
    "RobotHardware",
    "build_hardware",
]


def build_hardware(joints: list[JointSpec]) -> RobotHardware:
    """Resolve ROBOT_HARDWARE env to a concrete driver. Default mock keeps
    the demo zero-config; real drivers are late-imported so their deps
    (dynamixel-sdk, lerobot) stay optional."""
    backend = os.getenv("ROBOT_HARDWARE", "mock").lower()
    port = os.getenv("ROBOT_HARDWARE_PORT", "/dev/ttyUSB0")
    if backend == "mock":
        return MockHardware(joints)
    if backend == "dynamixel":
        from .dynamixel import DynamixelHardware

        baud = int(os.getenv("ROBOT_HARDWARE_BAUD", "1000000"))
        logger.info("hardware: dynamixel %s @ %d baud", port, baud)
        return DynamixelHardware(joints, port=port, baudrate=baud)
    if backend == "lerobot":
        from .lerobot import LeRobotHardware

        logger.info("hardware: lerobot %s", port)
        return LeRobotHardware(joints, port=port)
    raise RuntimeError(f"unknown ROBOT_HARDWARE: {backend!r}")
