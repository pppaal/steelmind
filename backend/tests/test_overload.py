"""Overload protective stop: sustained over-limit joint effort latches a
hardware stop, mirroring the operator E-stop. Driven directly on AppContext
so the policy is tested without the background sensor loop's timing."""

import pytest

from backend.hardware.base import HardwareSnapshot, JointSpec, JointState
from backend.hardware.mock import MockHardware
from backend.main.context import AppContext


def _snapshot(efforts: dict[str, float], *, estopped: bool = False) -> HardwareSnapshot:
    joints = {n: JointState(name=n, position=0.0, effort=e) for n, e in efforts.items()}
    return HardwareSnapshot(timestamp_monotonic=0.0, joints=joints, estopped=estopped)


async def _ctx_with_joint(max_effort: float) -> AppContext:
    ctx = AppContext()
    ctx.joints = [
        JointSpec(name="j1", hardware_id="1", lower_limit=-1.0, upper_limit=1.0, max_effort=max_effort)
    ]
    ctx.hardware = MockHardware(ctx.joints)
    await ctx.hardware.init()
    return ctx


@pytest.mark.asyncio
async def test_sustained_overload_trips_protective_stop() -> None:
    ctx = await _ctx_with_joint(max_effort=1.0)
    over = _snapshot({"j1": 2.0})
    # Default grace is 3 frames: the first two don't trip.
    await ctx._check_overload(over)
    await ctx._check_overload(over)
    assert ctx.state_machine.status.error is None
    assert ctx.metrics.overload_stops_total == 0
    # Third consecutive over-limit frame trips the protective stop.
    await ctx._check_overload(over)
    assert "overload" in (ctx.state_machine.status.error or "")
    assert "j1" in (ctx.state_machine.status.error or "")
    assert ctx.metrics.overload_stops_total == 1
    assert ctx.hardware._estopped is True


@pytest.mark.asyncio
async def test_transient_spike_does_not_trip() -> None:
    ctx = await _ctx_with_joint(max_effort=1.0)
    await ctx._check_overload(_snapshot({"j1": 5.0}))  # count -> 1
    await ctx._check_overload(_snapshot({"j1": 0.0}))  # back under -> counter cleared
    await ctx._check_overload(_snapshot({"j1": 5.0}))  # count -> 1 again
    assert ctx.state_machine.status.error is None
    assert ctx.metrics.overload_stops_total == 0


@pytest.mark.asyncio
async def test_disabled_protection_never_trips() -> None:
    ctx = await _ctx_with_joint(max_effort=0.0)  # 0 disables protection
    for _ in range(10):
        await ctx._check_overload(_snapshot({"j1": 9999.0}))
    assert ctx.state_machine.status.error is None
    assert ctx.metrics.overload_stops_total == 0


@pytest.mark.asyncio
async def test_already_estopped_snapshot_is_skipped() -> None:
    ctx = await _ctx_with_joint(max_effort=1.0)
    for _ in range(5):
        await ctx._check_overload(_snapshot({"j1": 2.0}, estopped=True))
    assert ctx.state_machine.status.error is None
    assert ctx.metrics.overload_stops_total == 0
