"""E-stop endpoint behavior: latches via /estop, clears via /estop/clear,
disables the active behavior, force-transitions to IDLE."""

from fastapi.testclient import TestClient


def test_estop_force_transitions_to_idle(fresh_app: TestClient) -> None:
    # Drive into STANDING first.
    fresh_app.post("/command", json={"command": "stand"})
    r = fresh_app.post("/estop")
    assert r.status_code == 200
    body = r.json()
    assert body["estopped"] is True
    assert fresh_app.get("/status").json()["state"] == "IDLE"


def test_estop_clears(fresh_app: TestClient) -> None:
    fresh_app.post("/estop")
    r = fresh_app.post("/estop/clear")
    assert r.status_code == 200
    assert r.json()["estopped"] is False


def test_estop_requires_operator(fresh_app: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("API_TOKEN", "secret")
    # No token → 401 even though auth is configured.
    r = fresh_app.post("/estop")
    assert r.status_code == 401
    # With token → 200.
    r2 = fresh_app.post("/estop", headers={"Authorization": "Bearer secret"})
    assert r2.status_code == 200
