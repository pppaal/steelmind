"""Cartesian safety zones (virtual walls): point checks, config parsing,
trajectory path gating, and the /reach + /keyframes 422 block."""

import math

from fastapi.testclient import TestClient

from backend.kinematics import Link, PlanarChain
from backend.preview import trajectory_zone_violation
from backend.trajectory import linear
from backend.zones import SafetyZone, zone_from_config


def test_zone_bounds_and_radius_and_keepout() -> None:
    z = SafetyZone(
        min_x=-1.0, max_x=1.0, min_y=0.0, max_y=2.0,
        min_radius=0.2, keepout=((0.4, 0.4, 0.6, 0.6),),
    )
    assert z.violation(0.5, 1.0) is None  # safe
    assert "below min_y" in z.violation(0.5, -0.1)
    assert "above max_x" in z.violation(1.5, 1.0)
    assert "keep-out radius" in z.violation(0.05, 0.05)
    assert "keep-out box" in z.violation(0.5, 0.5)


def test_zone_from_config_parses_block() -> None:
    z = zone_from_config({
        "chain": {"base": [0.1, 0.0]},
        "safety_zone": {"min_y": 0.0, "keepout": [[0, 0, 1, 1]]},
    })
    assert z is not None
    assert z.min_y == 0.0
    assert z.base_x == 0.1
    assert z.keepout == ((0.0, 0.0, 1.0, 1.0),)


def test_zone_from_config_absent_is_none() -> None:
    assert zone_from_config({"chain": {"base": [0, 0]}}) is None


def test_trajectory_zone_violation_detects_floor_breach() -> None:
    chain = PlanarChain(links=[Link("a", 1.0)])
    zone = SafetyZone(min_y=0.0)
    # Sweep the tip from +x down to -y: angle 0 → -90° dips below the floor.
    traj = linear({"a": 0.0}, {"a": -math.pi / 2}, duration=1.0)
    assert trajectory_zone_violation(traj, chain, zone, hz=20.0) is not None
    # A move that stays in the upper half-plane is fine.
    safe = linear({"a": 0.0}, {"a": math.pi / 4}, duration=1.0)
    assert trajectory_zone_violation(safe, chain, zone, hz=20.0) is None


def test_reach_blocked_by_safety_zone(so100_app: TestClient) -> None:
    import backend.main as main

    # Install a zone that forbids the lower half-plane (a floor at y=0).
    main.ctx.safety_zone = SafetyZone(min_y=0.0, base_x=0.0, base_y=0.0)
    # Target below the floor → blocked with 422, robot stays IDLE.
    r = main_post_reach(so100_app, x=0.1, y=-0.2)
    assert r.status_code == 422
    assert "safety zone" in r.json()["detail"]
    assert so100_app.get("/status").json()["state"] == "IDLE"


def test_reach_dry_run_reports_wall(so100_app: TestClient) -> None:
    import backend.main as main

    main.ctx.safety_zone = SafetyZone(min_y=0.0)
    body = main_post_reach(so100_app, x=0.1, y=-0.2, dry_run=True).json()
    assert any(v["kind"] == "wall" for v in body["preview"]["violations"])
    assert body["preview"]["ok"] is False


def test_workspace_includes_zone(so100_app: TestClient) -> None:
    import backend.main as main

    main.ctx.safety_zone = SafetyZone(min_y=0.0, keepout=((0, 0, 0.1, 0.1),))
    env = so100_app.get("/workspace").json()
    assert "zone" in env and env["zone"]["min_y"] == 0.0


def main_post_reach(client: TestClient, **body):
    return client.post("/reach", json=body)
