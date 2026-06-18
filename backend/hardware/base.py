"""Hardware abstraction layer for steelmind.

A RobotHardware implementation is the single source of truth for what the
robot is doing physically: joint positions/velocities/efforts and the IMU.
Higher layers (state machine, behaviors, trajectory player) never touch a
servo directly — they talk to this interface so the same code runs against
the MockHardware simulator and a real Dynamixel/LeRobot bus."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class JointSpec:
    """Static description of a single joint loaded from robot config."""

    name: str
    # Hardware-side identifier. Dynamixel = motor ID (int as str OK).
    hardware_id: str
    # Soft limits in radians. Always clamped at the HAL.
    lower_limit: float
    upper_limit: float
    # Max commanded angular velocity (rad/s). The HAL slews toward target
    # at this rate so a step input doesn't snap the joint instantly.
    max_velocity: float = 3.0
    # Overload threshold (same unit as JointState.effort). When > 0, sustained
    # effort above this trips a protective stop. 0 disables overload protection
    # for this joint (the default, so configs that don't set it are unaffected).
    max_effort: float = 0.0
    # Calibration offset (rad) — added to commanded target before writing,
    # subtracted from measured position before reporting. Lets you zero a
    # joint without re-mounting the servo horn.
    offset: float = 0.0
    # Optional flip: some servos run "backwards" relative to URDF convention.
    invert: bool = False

    def clamp(self, value: float) -> float:
        return max(self.lower_limit, min(self.upper_limit, value))


@dataclass
class JointState:
    name: str
    position: float  # radians, in the URDF / behavior frame (offset already removed)
    velocity: float = 0.0
    effort: float = 0.0


@dataclass
class IMUReading:
    orientation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    angular_velocity: tuple[float, float, float] = (0.0, 0.0, 0.0)
    linear_acceleration: tuple[float, float, float] = (0.0, 0.0, 9.81)


@dataclass
class HardwareSnapshot:
    """One sample of the entire robot's state. Produced by HAL.read()."""

    timestamp_monotonic: float
    joints: dict[str, JointState] = field(default_factory=dict)
    imu: IMUReading = field(default_factory=IMUReading)
    battery_voltage: float = 24.0
    battery_percent: float = 100.0
    enabled: bool = False
    estopped: bool = False
    # Free-form per-implementation health field — set when the HAL knows
    # something is wrong but it isn't fatal enough to E-stop. Surface this
    # in /health and the UI.
    warnings: tuple[str, ...] = ()


class HardwareError(Exception):
    """Driver-level failure. Distinct from logical state machine errors."""


class RobotHardware(ABC):
    """The contract every backend implementation must honor.

    Implementations store their joint list in `_joints` and a name→spec map
    in `_joints_by_name`; the concrete update_specs() below swaps both so
    runtime recalibration doesn't need to reopen the bus."""

    _joints: list[JointSpec]
    _joints_by_name: dict[str, JointSpec]

    @property
    @abstractmethod
    def joints(self) -> list[JointSpec]: ...

    def update_specs(self, joints: list[JointSpec]) -> None:
        """Hot-swap joint specs (e.g. after a calibration change). Only the
        offsets/limits change — joint identity (name, hardware_id) must be
        stable, so no bus re-init is required."""
        self._joints = list(joints)
        self._joints_by_name = {j.name: j for j in joints}

    @abstractmethod
    async def init(self) -> None:
        """Open the bus, query firmware, set torque-enable, etc.

        Idempotent: callers may invoke multiple times."""

    @abstractmethod
    async def close(self) -> None:
        """Disable torque and release the bus. Idempotent."""

    @abstractmethod
    async def read(self) -> HardwareSnapshot:
        """Return one full snapshot. MUST be safe to call at sensor cadence
        (default 20 Hz) without blocking other coroutines for long."""

    @abstractmethod
    async def write(self, targets: dict[str, float]) -> None:
        """Send position targets (rad, behavior frame) to the named joints.

        Unknown joint names are silently ignored. Implementations are
        expected to clamp via JointSpec.clamp() and respect max_velocity by
        slewing rather than stepping."""

    @abstractmethod
    async def enable(self) -> None:
        """Energize the motors. Called when the state machine first leaves
        IDLE."""

    @abstractmethod
    async def disable(self) -> None:
        """De-energize the motors. Called on graceful shutdown and on the
        IDLE transition. NOT an emergency stop — see estop()."""

    @abstractmethod
    async def estop(self) -> None:
        """Immediate, latching motor cut. The HAL MUST refuse writes until
        clear_estop() is called. Safer than disable() because it cannot be
        re-enabled implicitly by a stray write()."""

    @abstractmethod
    async def clear_estop(self) -> None:
        """Operator-initiated reset. Implementation should re-check bus
        health before clearing — never auto-clear from a write() side
        effect."""
