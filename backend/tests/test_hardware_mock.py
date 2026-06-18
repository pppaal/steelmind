"""MockHardware semantics: clamping, slewing, estop latching, snapshot shape."""

import asyncio
import math
import time

import pytest

from backend.hardware.base import JointSpec
from backend.hardware.mock import MockHardware


def _hw() -> MockHardware:
    return MockHardware([
        JointSpec(name="a", hardware_id="1", lower_limit=-1.0, upper_limit=1.0, max_velocity=2.0),
        JointSpec(name="b", hardware_id="2", lower_limit=-math.pi, upper_limit=math.pi, max_velocity=10.0),
    ])


@pytest.mark.asyncio
async def test_write_clamps_to_joint_limits() -> None:
    hw = _hw()
    await hw.init()
    await hw.enable()
    await hw.write({"a": 5.0})
    snap = await hw.read()
    # Slewing means we don't reach the target in one tick, but the *target*
    # is clamped, so we move toward 1.0 (not 5.0).
    assert snap.joints["a"].position <= 1.0
    assert "clamped: a" in snap.warnings


@pytest.mark.asyncio
async def test_slew_respects_max_velocity() -> None:
    hw = _hw()
    await hw.init()
    await hw.enable()
    await hw.write({"a": 1.0})
    # Read once to set the clock baseline.
    await hw.read()
    # Sleep a known interval; with max_velocity=2 rad/s, in 50 ms we should
    # cover at most 0.1 rad.
    await asyncio.sleep(0.05)
    snap = await hw.read()
    assert snap.joints["a"].position <= 0.2  # generous bound for jitter


@pytest.mark.asyncio
async def test_estop_latches_and_blocks_writes() -> None:
    hw = _hw()
    await hw.init()
    await hw.enable()
    await hw.estop()
    snap = await hw.read()
    assert snap.estopped is True
    assert snap.enabled is False
    # Writes are silently dropped while latched and surface as a warning.
    await hw.write({"a": 0.5})
    snap_after_write = await hw.read()
    all_warnings = snap.warnings + snap_after_write.warnings
    assert any("estop" in w for w in all_warnings)
    # Re-enable should refuse until cleared.
    await hw.enable()
    snap2 = await hw.read()
    assert snap2.enabled is False
    # Clear and now enable works.
    await hw.clear_estop()
    await hw.enable()
    snap3 = await hw.read()
    assert snap3.enabled is True


@pytest.mark.asyncio
async def test_unknown_joint_silently_dropped() -> None:
    hw = _hw()
    await hw.init()
    await hw.enable()
    await hw.write({"ghost": 0.5, "a": 0.1})
    snap = await hw.read()
    assert "ghost" not in snap.joints
    assert "a" in snap.joints


@pytest.mark.asyncio
async def test_snapshot_timestamp_advances() -> None:
    hw = _hw()
    await hw.init()
    s1 = await hw.read()
    await asyncio.sleep(0.01)
    s2 = await hw.read()
    assert s2.timestamp_monotonic > s1.timestamp_monotonic


@pytest.mark.asyncio
async def test_disable_freezes_positions() -> None:
    hw = _hw()
    await hw.init()
    await hw.enable()
    await hw.write({"b": 1.0})
    await hw.read()
    await asyncio.sleep(0.05)
    p1 = (await hw.read()).joints["b"].position
    await hw.disable()
    await asyncio.sleep(0.05)
    p2 = (await hw.read()).joints["b"].position
    # Disabled motors don't move toward target.
    assert abs(p2 - p1) < 0.01
    _ = time


@pytest.mark.asyncio
async def test_effort_rises_with_tracking_error_and_is_zero_at_rest() -> None:
    hw = _hw()
    await hw.init()
    await hw.enable()
    # Far target → large tracking error → non-zero effort while catching up.
    await hw.write({"b": 3.0})
    await hw.read()  # baseline clock
    moving = (await hw.read()).joints["b"].effort
    assert moving > 0.0
    # Let it settle onto the (clamped) target, then effort decays toward zero.
    for _ in range(40):
        await asyncio.sleep(0.02)
        snap = await hw.read()
    assert snap.joints["b"].effort < moving
    assert snap.joints["b"].effort < 0.05


@pytest.mark.asyncio
async def test_effort_zero_when_estopped() -> None:
    hw = _hw()
    await hw.init()
    await hw.enable()
    await hw.write({"b": 3.0})
    await hw.estop()
    snap = await hw.read()
    assert all(js.effort == 0.0 for js in snap.joints.values())
