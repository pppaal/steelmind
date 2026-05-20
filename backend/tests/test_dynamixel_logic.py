"""Dynamixel driver logic, verified WITHOUT hardware.

Two layers:
1. Pure conversion functions (rad↔counts, offset/invert round-trip).
2. The sync read/write methods, exercised against a fake dynamixel_sdk
   injected into sys.modules — so the param packing, ID mapping, and
   counts conversion are all checked even though no servo exists.
"""

import math
import sys
import types

import pytest

from backend.hardware.base import JointSpec
from backend.hardware.dynamixel import (
    _CENTER,
    _counts_to_rad,
    _rad_to_counts,
    from_motor_counts,
    to_motor_counts,
)


def _spec(**kw) -> JointSpec:
    base = dict(name="j", hardware_id="1", lower_limit=-math.pi, upper_limit=math.pi)
    base.update(kw)
    return JointSpec(**base)


# ---- pure conversion ----------------------------------------------------------

def test_center_is_zero_rad() -> None:
    assert _counts_to_rad(_CENTER) == 0.0
    assert _rad_to_counts(0.0) == _CENTER


def test_counts_round_trip() -> None:
    for counts in (0, 1024, _CENTER, 3072, 4095):
        rad = _counts_to_rad(counts)
        assert _rad_to_counts(rad) == counts


def test_half_turn_is_quarter_range() -> None:
    # +π/2 should be a quarter-rev above center.
    assert _rad_to_counts(math.pi / 2) == _CENTER + _COUNTS_QUARTER()


def _COUNTS_QUARTER() -> int:
    return 4096 // 4


# One encoder count is the irreducible round-trip error (4096 counts/rev).
_ONE_COUNT_RAD = 2 * math.pi / 4096


def test_offset_round_trip() -> None:
    spec = _spec(offset=math.radians(30))
    # A logical 0 maps to counts; reading those back returns ~0, within one
    # count of encoder resolution (quantization is unavoidable on real HW).
    counts = to_motor_counts(0.0, spec)
    assert abs(from_motor_counts(counts, spec)) <= _ONE_COUNT_RAD


def test_invert_round_trip() -> None:
    spec = _spec(invert=True)
    counts = to_motor_counts(0.5, spec)
    assert abs(from_motor_counts(counts, spec) - 0.5) < 1e-3


def test_invert_actually_flips_direction() -> None:
    plain = _spec(invert=False)
    flipped = _spec(invert=True)
    # +0.5 rad logical lands on opposite sides of center for inverted vs not.
    assert (to_motor_counts(0.5, plain) - _CENTER) == -(to_motor_counts(0.5, flipped) - _CENTER)


def test_offset_and_invert_compose() -> None:
    spec = _spec(offset=math.radians(45), invert=True)
    for logical in (-1.0, -0.2, 0.0, 0.3, 1.1):
        counts = to_motor_counts(logical, spec)
        assert abs(from_motor_counts(counts, spec) - logical) < 1e-3


# ---- fake-SDK integration -----------------------------------------------------


class _FakePortHandler:
    def __init__(self, port: str) -> None:
        self.port = port

    def openPort(self) -> bool:
        return True

    def setBaudRate(self, _b: int) -> bool:
        return True

    def closePort(self) -> None:
        pass


class _FakePacketHandler:
    def __init__(self, _v: float) -> None:
        self.torque_writes: list[tuple[int, int]] = []

    def write1ByteTxRx(self, _port, dxl_id, _addr, value):
        self.torque_writes.append((dxl_id, value))
        return 0, 0  # comm_result, dxl_error — both OK


class _FakeGroupSyncWrite:
    def __init__(self, _port, _packet, _addr, _len) -> None:
        self.params: dict[int, bytes] = {}
        self.tx_count = 0

    def clearParam(self) -> None:
        self.params.clear()

    def addParam(self, dxl_id, data) -> bool:
        self.params[dxl_id] = data
        return True

    def txPacket(self):
        self.tx_count += 1
        return 0


class _FakeGroupSyncRead:
    def __init__(self, _port, _packet, _addr, _len) -> None:
        self.ids: list[int] = []
        # Test injects raw counts keyed by id.
        self.data: dict[int, int] = {}

    def addParam(self, dxl_id) -> bool:
        self.ids.append(dxl_id)
        return True

    def txRxPacket(self):
        return 0

    def getData(self, dxl_id, _addr, _len) -> int:
        return self.data.get(dxl_id, _CENTER)


@pytest.fixture()
def fake_sdk(monkeypatch: pytest.MonkeyPatch):
    mod = types.ModuleType("dynamixel_sdk")
    mod.PortHandler = _FakePortHandler
    mod.PacketHandler = _FakePacketHandler
    mod.GroupSyncWrite = _FakeGroupSyncWrite
    mod.GroupSyncRead = _FakeGroupSyncRead
    monkeypatch.setitem(sys.modules, "dynamixel_sdk", mod)
    return mod


@pytest.mark.asyncio
async def test_init_pings_all_ids(fake_sdk) -> None:
    from backend.hardware.dynamixel import DynamixelHardware

    joints = [_spec(name="a", hardware_id="1"), _spec(name="b", hardware_id="2")]
    hw = DynamixelHardware(joints, port="/dev/fake")
    await hw.init()
    assert hw._group_sync_read.ids == [1, 2]
    await hw.close()


@pytest.mark.asyncio
async def test_write_packs_unsigned_counts(fake_sdk) -> None:
    from backend.hardware.dynamixel import DynamixelHardware

    joints = [_spec(name="a", hardware_id="7")]
    hw = DynamixelHardware(joints, port="/dev/fake")
    await hw.init()
    await hw.enable()
    await hw.write({"a": 0.0})  # logical 0 → center counts
    packed = hw._group_sync_write.params[7]
    counts = int.from_bytes(packed, "little", signed=False)
    assert counts == _CENTER
    await hw.close()


@pytest.mark.asyncio
async def test_read_converts_counts_to_logical(fake_sdk) -> None:
    from backend.hardware.dynamixel import DynamixelHardware

    joints = [_spec(name="a", hardware_id="3", offset=math.radians(90))]
    hw = DynamixelHardware(joints, port="/dev/fake")
    await hw.init()
    # Simulate the servo sitting at center counts; with a +90° offset the
    # logical position should read -90°.
    hw._group_sync_read.data[3] = _CENTER
    snap = await hw.read()
    assert abs(snap.joints["a"].position - math.radians(-90)) < 1e-3
    await hw.close()


@pytest.mark.asyncio
async def test_estop_blocks_write(fake_sdk) -> None:
    from backend.hardware.dynamixel import DynamixelHardware

    joints = [_spec(name="a", hardware_id="1")]
    hw = DynamixelHardware(joints, port="/dev/fake")
    await hw.init()
    await hw.enable()
    await hw.estop()
    hw._group_sync_write.params.clear()
    await hw.write({"a": 0.5})
    # estop latched → no sync write issued.
    assert hw._group_sync_write.params == {}
    await hw.close()
