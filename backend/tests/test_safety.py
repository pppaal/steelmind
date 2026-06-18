"""Joint clamping, slewing, and watchdog liveness."""

import asyncio

import pytest

from backend.hardware.base import JointSpec
from backend.safety import Watchdog, clamp_targets, overloaded_joints, slew_toward


def test_overloaded_joints_reports_over_limit() -> None:
    joints = {
        "a": JointSpec(name="a", hardware_id="1", lower_limit=-1, upper_limit=1, max_effort=5.0),
        "b": JointSpec(name="b", hardware_id="2", lower_limit=-1, upper_limit=1, max_effort=5.0),
    }
    assert overloaded_joints({"a": 6.0, "b": 1.0}, joints) == ["a"]


def test_overloaded_joints_ignores_disabled_protection() -> None:
    # max_effort defaults to 0 → protection disabled, never reported.
    joints = {"a": JointSpec(name="a", hardware_id="1", lower_limit=-1, upper_limit=1)}
    assert overloaded_joints({"a": 9999.0}, joints) == []


def _joints() -> dict[str, JointSpec]:
    return {
        "a": JointSpec(name="a", hardware_id="1", lower_limit=-1.0, upper_limit=1.0, max_velocity=2.0),
    }


def test_clamp_reports_clamped_joints() -> None:
    out, clamped = clamp_targets({"a": 5.0}, _joints())
    assert out["a"] == 1.0
    assert clamped == ["a"]


def test_clamp_passes_in_range() -> None:
    out, clamped = clamp_targets({"a": 0.5}, _joints())
    assert out["a"] == 0.5
    assert clamped == []


def test_clamp_drops_unknown_joints() -> None:
    out, _ = clamp_targets({"ghost": 0.0}, _joints())
    assert out == {}


def test_slew_caps_per_tick_delta() -> None:
    # max_velocity=2 rad/s, dt=0.05 → max step 0.1 rad
    new = slew_toward({"a": 0.0}, {"a": 5.0}, _joints(), dt=0.05)
    assert abs(new["a"] - 0.1) < 1e-9


def test_slew_reaches_when_within_step() -> None:
    new = slew_toward({"a": 0.0}, {"a": 0.05}, _joints(), dt=0.05)
    assert new["a"] == 0.05


@pytest.mark.asyncio
async def test_watchdog_fires_on_starvation() -> None:
    fired = asyncio.Event()

    async def trip() -> None:
        fired.set()

    dog = Watchdog(expire_seconds=0.1, on_expire=trip)
    dog.start()
    # Don't feed it — should fire within ~100 ms.
    await asyncio.wait_for(fired.wait(), timeout=1.0)
    await dog.stop()


@pytest.mark.asyncio
async def test_watchdog_quiet_when_fed() -> None:
    fired = asyncio.Event()

    async def trip() -> None:
        fired.set()

    dog = Watchdog(expire_seconds=0.2, on_expire=trip)
    dog.start()
    # Feed every 50 ms for 300 ms — much faster than expiry.
    for _ in range(6):
        dog.feed()
        await asyncio.sleep(0.05)
    assert not fired.is_set()
    await dog.stop()
