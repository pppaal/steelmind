"""Trajectory dry-run simulation (pure) and the /reach, /keyframes dry_run API."""

import math

from fastapi.testclient import TestClient

from backend.hardware.base import JointSpec
from backend.preview import simulate_trajectory
from backend.trajectory import linear


def _joints() -> dict[str, JointSpec]:
    return {
        "a": JointSpec(
            name="a", hardware_id="1", lower_limit=-1.0, upper_limit=1.0, max_velocity=2.0
        ),
    }


def test_preview_clean_in_range_slow_move() -> None:
    # 0 -> 0.5 over 2 s: inside limits and well under 2 rad/s.
    traj = linear({"a": 0.0}, {"a": 0.5}, duration=2.0)
    out = simulate_trajectory(traj, _joints(), hz=20.0)
    assert out["ok"] is True
    assert out["violations"] == []
    assert out["joints"]["a"]["clamped"] is False


def test_preview_flags_limit_clamp() -> None:
    # Target 5.0 is way past the +1.0 soft limit.
    traj = linear({"a": 0.0}, {"a": 5.0}, duration=2.0)
    out = simulate_trajectory(traj, _joints(), hz=20.0)
    assert out["ok"] is False
    assert any(v["kind"] == "limit" for v in out["violations"])
    assert out["joints"]["a"]["clamped"] is True


def test_preview_flags_velocity_rate_limit() -> None:
    # 0 -> 1.0 in 0.1 s ≈ 10 rad/s, far over max_velocity 2.0. Stays in range,
    # so ok is still True (a velocity cap only slows, doesn't clamp the pose).
    traj = linear({"a": 0.0}, {"a": 1.0}, duration=0.1)
    out = simulate_trajectory(traj, _joints(), hz=50.0)
    assert out["ok"] is True
    assert any(v["kind"] == "velocity" for v in out["violations"])
    assert out["joints"]["a"]["peak_velocity"] > 2.0


def test_preview_includes_path_with_chain() -> None:
    from backend.kinematics import Link, PlanarChain

    chain = PlanarChain(links=[Link("a", 1.0)])
    traj = linear({"a": 0.0}, {"a": math.pi / 2}, duration=1.0)
    out = simulate_trajectory(traj, _joints(), hz=20.0, chain=chain)
    assert "path" in out
    assert out["path"]["start"][0] == 1.0  # tip at (1, 0) when angle 0


def test_reach_dry_run_does_not_move(so100_app: TestClient) -> None:
    r = so100_app.post("/reach", json={"x": 0.15, "y": 0.1, "dry_run": True})
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True
    assert "preview" in body and "path" in body["preview"]
    # A dry run must not drive the robot: it stays IDLE.
    assert so100_app.get("/status").json()["state"] == "IDLE"


def test_keyframes_dry_run_does_not_move(so100_app: TestClient) -> None:
    so100_app.post("/keyframes/home")
    r = so100_app.post("/keyframes/play", json={"names": ["home"], "dry_run": True})
    assert r.status_code == 200
    assert r.json()["dry_run"] is True
    assert so100_app.get("/status").json()["state"] == "IDLE"
