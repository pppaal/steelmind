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


def test_jam_fault_spikes_effort() -> None:
    sim = _sim(gravity=0.0)
    sim._enabled = True
    sim._targets["j"] = 1.5
    sim.inject_fault("j", "jam")
    for _ in range(50):
        sim._integrate(0.02)
    # The joint can't move but the motor strains toward the target.
    assert sim._pos["j"] == pytest.approx(0.0, abs=1e-9)
    assert sim._effort["j"] > 1.0
    sim.clear_faults()
    for _ in range(300):
        sim._integrate(0.02)
    assert sim._pos["j"] == pytest.approx(1.5, abs=1e-2)  # recovers after clear


def test_disturbance_fault_perturbs_joint() -> None:
    sim = _sim(gravity=0.0)
    sim._enabled = True
    sim._targets["j"] = 0.0
    sim.inject_fault("j", "disturbance", 20.0)  # constant external torque
    for _ in range(300):
        sim._integrate(0.02)
    # A steady push holds the joint off zero against the motor.
    assert abs(sim._pos["j"]) > 0.05
    assert sim.faults()["disturbance"] == {"j": 20.0}


def test_inject_fault_validates() -> None:
    sim = _sim(gravity=0.0)
    with pytest.raises(ValueError, match="unknown joint"):
        sim.inject_fault("nope", "jam")
    with pytest.raises(ValueError, match="unknown fault kind"):
        sim.inject_fault("j", "explode")


def test_sim_fault_api_round_trip(sim_app: TestClient) -> None:
    assert sim_app.get("/sim").json()["sim"] is True
    r = sim_app.post("/sim/fault", json={"joint": "hip_left", "kind": "jam"})
    assert r.status_code == 200
    assert "hip_left" in r.json()["faults"]["jammed"]
    assert sim_app.post("/sim/fault", json={"joint": "ghost", "kind": "jam"}).status_code == 404
    assert sim_app.post("/sim/clear-faults").json()["faults"]["jammed"] == []


def test_sim_fault_unavailable_on_mock(fresh_app: TestClient) -> None:
    assert fresh_app.get("/sim").json()["sim"] is False
    assert fresh_app.post("/sim/fault", json={"joint": "hip_left", "kind": "jam"}).status_code == 400


def test_jam_trips_overload_protective_stop_end_to_end(app_booter, tmp_path) -> None:
    import json
    import time

    cfg = tmp_path / "armcfg.json"
    cfg.write_text(json.dumps({
        "name": "fault-demo",
        "joints": [{
            "name": "j1", "hardware_id": "1",
            "lower_limit_deg": -180, "upper_limit_deg": 180,
            "max_velocity": 3.0, "max_effort": 2.0,  # low → easy to trip
        }],
    }))
    with app_booter(ROBOT_HARDWARE="sim", ROBOT_CONFIG=str(cfg)) as c:
        # Jam the joint, then command it far away — the motor strains past
        # max_effort and the overload reflex must latch a protective stop.
        assert c.post("/sim/fault", json={"joint": "j1", "kind": "jam"}).status_code == 200
        # delta within MAX_JOG_RAD; jammed at 0 → motor effort ≈ kp*0.3 ≫ 2.0.
        assert c.post("/jog", json={"joint": "j1", "delta": 0.3}).status_code == 200
        for _ in range(60):  # up to ~6 s for the sensor loop to trip
            err = c.get("/status").json().get("error")
            if err and "overload" in err:
                break
            time.sleep(0.1)
        else:
            raise AssertionError("overload protective stop never fired")


def test_gravity_zero_at_hanging_pose() -> None:
    # A joint commanded to 0 (hanging) has no gravity load → no sag, ~0 effort.
    sim = _sim(gravity=6.0)
    sim._enabled = True
    sim._targets["j"] = 0.0
    for _ in range(200):
        sim._integrate(0.02)
    assert sim._pos["j"] == pytest.approx(0.0, abs=1e-3)
    assert sim._effort["j"] < 0.05
