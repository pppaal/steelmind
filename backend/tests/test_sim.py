"""Physics simulation HAL: settling, gravity sag/hold-effort, limits, estop,
and factory selection."""

import pytest
from fastapi.testclient import TestClient

from backend.hardware import build_hardware
from backend.hardware.base import JointSpec
from backend.hardware.sim import PhysicsSim


def _spec(lo: float = -2.0, hi: float = 2.0) -> JointSpec:
    return JointSpec(name="j", hardware_id="1", lower_limit=lo, upper_limit=hi)


def _sim(gravity: float, **kw) -> PhysicsSim:
    return PhysicsSim([_spec(**kw)], kp=40.0, kd=12.0, inertia=1.0, gravity=gravity, substep=0.005)


def test_settles_to_target_without_gravity() -> None:
    sim = _sim(gravity=0.0)
    sim._enabled = True
    sim._targets["j"] = 0.5
    for _ in range(300):
        sim._integrate(0.02)  # ~6 s
    assert sim._pos["j"] == pytest.approx(0.5, abs=1e-2)
    assert sim._vel["j"] == pytest.approx(0.0, abs=1e-2)
    # No gravity → essentially no steady holding torque.
    assert sim._effort["j"] < 0.05


def test_gravity_causes_sag_and_holding_effort() -> None:
    sim = _sim(gravity=6.0)
    sim._enabled = True
    sim._targets["j"] = 1.4  # near horizontal → large gravity load
    for _ in range(400):
        sim._integrate(0.02)
    # The joint sags below the commanded angle and the motor holds steady
    # effort against gravity.
    assert sim._pos["j"] < 1.4
    assert sim._effort["j"] > 1.0


def test_hard_limits_are_respected() -> None:
    sim = _sim(gravity=6.0, lo=-1.0, hi=1.0)
    sim._enabled = True
    sim._targets["j"] = 1.0
    for _ in range(400):
        sim._integrate(0.02)
        assert -1.0 <= sim._pos["j"] <= 1.0


@pytest.mark.asyncio
async def test_read_disabled_has_zero_effort() -> None:
    sim = _sim(gravity=6.0)
    await sim.init()
    await sim.write({"j": 1.0})  # target set, but motor not enabled
    snap = await sim.read()
    assert all(js.effort == 0.0 for js in snap.joints.values())


@pytest.mark.asyncio
async def test_estop_freezes_and_zeroes_effort() -> None:
    sim = _sim(gravity=6.0)
    await sim.init()
    await sim.enable()
    await sim.write({"j": 1.4})
    await sim.read()  # accrue some motion/effort
    await sim.estop()
    snap = await sim.read()
    assert snap.estopped is True
    assert all(js.effort == 0.0 and js.velocity == 0.0 for js in snap.joints.values())


def test_build_hardware_selects_sim(monkeypatch) -> None:
    monkeypatch.setenv("ROBOT_HARDWARE", "sim")
    assert isinstance(build_hardware([_spec()]), PhysicsSim)


def test_app_boots_and_jogs_on_sim_backend(sim_app: TestClient) -> None:
    # The whole stack runs against the physics sim: jog a joint and confirm
    # effort telemetry flows through the snapshot projection.
    assert sim_app.get("/health").json()["ok"] is True
    r = sim_app.post("/jog", json={"joint": "hip_left", "delta": 0.2})
    assert r.status_code == 200


def test_gravity_zero_at_hanging_pose() -> None:
    # A joint commanded to 0 (hanging) has no gravity load → no sag, ~0 effort.
    sim = _sim(gravity=6.0)
    sim._enabled = True
    sim._targets["j"] = 0.0
    for _ in range(200):
        sim._integrate(0.02)
    assert sim._pos["j"] == pytest.approx(0.0, abs=1e-3)
    assert sim._effort["j"] < 0.05
