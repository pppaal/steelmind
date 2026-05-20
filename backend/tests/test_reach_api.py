"""/fk and /reach endpoints. The default sim config has no chain (→ 400);
a fixture booting the SO-100 config exercises the real IK→trajectory path."""

import importlib
import os
import sys
import tempfile

import pytest
from fastapi.testclient import TestClient


def test_reach_without_chain_returns_400(fresh_app: TestClient) -> None:
    # sim_humanoid (the fresh_app default) ships no kinematic chain.
    assert fresh_app.post("/reach", json={"x": 0.1, "y": 0.1}).status_code == 400
    assert fresh_app.get("/fk").status_code == 400


@pytest.fixture()
def so100_app(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Boot the app against the SO-100 config, which has a planar chain."""
    fd, db = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setenv("JOURNAL_DB", db)
    for var in ("CALIBRATION_FILE", "KEYFRAMES_FILE"):
        f, p = tempfile.mkstemp(suffix=".json")
        os.close(f)
        os.unlink(p)
        monkeypatch.setenv(var, p)
    monkeypatch.setenv("ROBOT_CONFIG", "backend/configs/so100_arm.json")
    for name in list(sys.modules):
        if name == "backend.main" or name.startswith("backend.main."):
            del sys.modules[name]
    main = importlib.import_module("backend.main")
    with TestClient(main.app) as client:
        yield client
    try:
        os.unlink(db)
    except OSError:
        pass


def test_fk_reports_position(so100_app: TestClient) -> None:
    body = so100_app.get("/fk").json()
    assert "x" in body and "y" in body
    # Arm starts at all-zero → fully extended along +x = sum of link lengths.
    assert abs(body["x"] - body["reach"]) < 1e-6


def test_reach_reachable_target(so100_app: TestClient) -> None:
    # A point comfortably inside the workspace (reach ≈ 0.316 m).
    r = so100_app.post("/reach", json={"x": 0.15, "y": 0.1})
    assert r.status_code == 200
    body = r.json()
    assert body["reached"] is True
    assert "angles" in body


def test_reach_unreachable_reports_false(so100_app: TestClient) -> None:
    r = so100_app.post("/reach", json={"x": 5.0, "y": 5.0})
    assert r.status_code == 200
    assert r.json()["reached"] is False
