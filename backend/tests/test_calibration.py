"""Calibration persistence + the /calibration & /jog endpoints."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from backend.calibration import Calibration


@pytest.mark.asyncio
async def test_persist_and_reload(tmp_path) -> None:
    path = tmp_path / "cal.json"
    c1 = Calibration(path)
    await c1.set_offset("shoulder_left", 0.25)
    await c1.set_many({"elbow_left": -0.1, "wrist_left": 0.05})
    # Fresh instance reads what the first wrote.
    c2 = Calibration(path)
    await c2.load()
    assert c2.offset_for("shoulder_left") == 0.25
    assert c2.offset_for("elbow_left") == -0.1
    assert c2.offset_for("missing") == 0.0


@pytest.mark.asyncio
async def test_clear(tmp_path) -> None:
    path = tmp_path / "cal.json"
    c = Calibration(path)
    await c.set_offset("a", 1.0)
    await c.clear()
    assert c.offsets == {}


@pytest.mark.asyncio
async def test_corrupt_file_loads_empty(tmp_path) -> None:
    path = tmp_path / "cal.json"
    path.write_text("{ this is not json")
    c = Calibration(path)
    await c.load()
    assert c.offsets == {}


@pytest.mark.asyncio
async def test_atomic_write_leaves_no_tmp(tmp_path) -> None:
    path = tmp_path / "cal.json"
    c = Calibration(path)
    await c.set_offset("a", 0.5)
    assert path.exists()
    assert not path.with_suffix(".json.tmp").exists()
    _ = asyncio


def test_jog_moves_joint(fresh_app: TestClient) -> None:
    # sim_humanoid has shoulder_right.
    r = fresh_app.post("/jog", json={"joint": "shoulder_right", "delta": 0.2})
    assert r.status_code == 200
    assert r.json()["joint"] == "shoulder_right"


def test_jog_rejects_unknown_joint(fresh_app: TestClient) -> None:
    r = fresh_app.post("/jog", json={"joint": "tail", "delta": 0.1})
    assert r.status_code == 404


def test_jog_rejects_oversized_delta(fresh_app: TestClient) -> None:
    r = fresh_app.post("/jog", json={"joint": "shoulder_right", "delta": 5.0})
    assert r.status_code == 400


def test_calibration_endpoints(fresh_app: TestClient) -> None:
    # Set then read back.
    r = fresh_app.post("/calibration", json={"offsets": {"shoulder_right": 0.1}})
    assert r.status_code == 200
    got = fresh_app.get("/calibration").json()
    assert got["offsets"]["shoulder_right"] == 0.1


def test_calibration_rejects_unknown_joint(fresh_app: TestClient) -> None:
    r = fresh_app.post("/calibration", json={"offsets": {"nonexistent": 0.1}})
    assert r.status_code == 400
