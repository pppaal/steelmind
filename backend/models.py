from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class RobotState(str, Enum):
    IDLE = "IDLE"
    WALKING = "WALKING"
    STANDING = "STANDING"
    EXECUTING = "EXECUTING"


class Vector3(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class SensorData(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    imu_orientation: Vector3 = Field(default_factory=Vector3)
    imu_angular_velocity: Vector3 = Field(default_factory=Vector3)
    imu_linear_acceleration: Vector3 = Field(default_factory=Vector3)
    joint_positions: dict[str, float] = Field(default_factory=dict)
    joint_velocities: dict[str, float] = Field(default_factory=dict)
    joint_efforts: dict[str, float] = Field(default_factory=dict)
    battery_voltage: float = 0.0
    battery_percent: float = 0.0


class RobotStatus(BaseModel):
    state: RobotState = RobotState.IDLE
    previous_state: RobotState | None = None
    current_behavior: str | None = None
    last_transition: datetime = Field(default_factory=lambda: datetime.now(UTC))
    error: str | None = None


class StateTransitionEvent(BaseModel):
    type: Literal["state_transition"] = "state_transition"
    from_state: RobotState
    to_state: RobotState
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reason: str | None = None


class SensorEvent(BaseModel):
    type: Literal["sensor"] = "sensor"
    data: SensorData


class StatusEvent(BaseModel):
    type: Literal["status"] = "status"
    status: RobotStatus


class BehaviorEvent(BaseModel):
    type: Literal["behavior"] = "behavior"
    name: str
    status: Literal["started", "running", "succeeded", "failed"]
    detail: str | None = None


class CommandRequest(BaseModel):
    command: str
    params: dict[str, Any] = Field(default_factory=dict)


class CommandResponse(BaseModel):
    ok: bool
    message: str | None = None
    status: RobotStatus
