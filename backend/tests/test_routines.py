"""Routine store + the save/run/delete API and step validation."""

import time

import pytest
from fastapi.testclient import TestClient

from backend.routines import RoutineStore


@pytest.mark.asyncio
async def test_store_persist_reload(tmp_path) -> None:
    path = tmp_path / "r.json"
    s1 = RoutineStore(path)
    await s1.save("greet", [{"type": "behavior", "behavior": "wave"}])
    s2 = RoutineStore(path)
    await s2.load()
    assert s2.names == ["greet"]
    assert s2.get("greet") == [{"type": "behavior", "behavior": "wave"}]


@pytest.mark.asyncio
async def test_store_delete(tmp_path) -> None:
    s = RoutineStore(tmp_path / "r.json")
    await s.save("x", [{"type": "wait", "seconds": 1}])
    assert await s.delete("x") is True
    assert await s.delete("x") is False


def test_save_and_list_routine(fresh_app: TestClient) -> None:
    body = {
        "steps": [
            {"type": "command", "command": "stand"},
            {"type": "behavior", "behavior": "wave"},
            {"type": "wait", "seconds": 0.1},
        ]
    }
    r = fresh_app.put("/routines/demo", json=body)
    assert r.status_code == 200
    assert r.json()["steps"] == 3
    listing = fresh_app.get("/routines").json()["routines"]
    assert "demo" in listing
    assert len(listing["demo"]) == 3


def test_save_rejects_unknown_behavior(fresh_app: TestClient) -> None:
    r = fresh_app.put("/routines/bad", json={"steps": [{"type": "behavior", "behavior": "moonwalk"}]})
    assert r.status_code == 400


def test_save_rejects_bad_step_type(fresh_app: TestClient) -> None:
    # Discriminated union rejects unknown type at validation → 422.
    r = fresh_app.put("/routines/bad", json={"steps": [{"type": "teleport"}]})
    assert r.status_code == 422


def test_run_unknown_routine_404(fresh_app: TestClient) -> None:
    assert fresh_app.post("/routines/ghost/run").status_code == 404


def test_run_routine_executes(fresh_app: TestClient) -> None:
    body = {
        "steps": [
            {"type": "command", "command": "stand"},
            {"type": "behavior", "behavior": "demo"},
            {"type": "command", "command": "idle"},
        ]
    }
    fresh_app.put("/routines/seq", json=body)
    r = fresh_app.post("/routines/seq/run")
    assert r.status_code == 200
    # The routine runs in the background; poll /status until it lands back at
    # IDLE (the final step) or time out.
    for _ in range(80):
        st = fresh_app.get("/status").json()
        if st["state"] == "IDLE" and st["current_behavior"] is None:
            break
        time.sleep(0.1)
    else:
        raise AssertionError("routine did not complete")


def test_delete_routine_api(fresh_app: TestClient) -> None:
    fresh_app.put("/routines/tmp", json={"steps": [{"type": "wait", "seconds": 0}]})
    assert fresh_app.delete("/routines/tmp").status_code == 200
    assert fresh_app.delete("/routines/tmp").status_code == 404
