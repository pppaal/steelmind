import pytest
from fastapi.testclient import TestClient

from backend import main


@pytest.fixture()
def client() -> TestClient:
    with TestClient(main.app) as c:
        yield c


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["state"] == "IDLE"


def test_status(client: TestClient) -> None:
    r = client.get("/status")
    assert r.status_code == 200
    assert r.json()["state"] == "IDLE"


def test_behaviors_listed(client: TestClient) -> None:
    r = client.get("/behaviors")
    assert r.status_code == 200
    names = {b["name"] for b in r.json()["behaviors"]}
    assert {"demo", "wave", "squat", "patrol", "dance"} <= names


def test_command_valid_chain(client: TestClient) -> None:
    r = client.post("/command", json={"command": "stand", "params": {}})
    assert r.status_code == 200
    assert r.json()["status"]["state"] == "STANDING"

    r = client.post("/command", json={"command": "walk", "params": {}})
    assert r.status_code == 200
    assert r.json()["status"]["state"] == "WALKING"


def test_command_invalid_transition(client: TestClient) -> None:
    # Drive back to IDLE via the valid chain regardless of prior test state.
    client.post("/command", json={"command": "stop", "params": {}})
    client.post("/command", json={"command": "idle", "params": {}})
    r = client.post("/command", json={"command": "walk", "params": {}})
    assert r.status_code == 409  # IDLE -> WALKING requires STANDING first


def test_command_unknown(client: TestClient) -> None:
    r = client.post("/command", json={"command": "fly", "params": {}})
    assert r.status_code == 400


def test_unknown_behavior(client: TestClient) -> None:
    r = client.post("/command", json={"command": "execute", "params": {"behavior": "moonwalk"}})
    assert r.status_code == 400


def test_ai_command_disabled_without_key(client: TestClient) -> None:
    # Test runs without ANTHROPIC_API_KEY so AICommander is disabled.
    r = client.post("/ai-command", json={"text": "stand up"})
    assert r.status_code == 503


def test_ai_reset_endpoint(client: TestClient) -> None:
    r = client.post("/ai-reset")
    assert r.status_code == 200
    assert r.json()["ai_history"] == 0


def test_health_exposes_ai_fields(client: TestClient) -> None:
    body = client.get("/health").json()
    assert "ai_enabled" in body
    assert "ai_history" in body


def test_metrics_endpoint(client: TestClient) -> None:
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    body = r.text
    assert "steelmind_transitions_total" in body
    assert "steelmind_ws_clients" in body


def test_journal_endpoints(client: TestClient) -> None:
    # Drive a couple of transitions so the journal has something to return.
    client.post("/command", json={"command": "stop", "params": {}})
    client.post("/command", json={"command": "idle", "params": {}})
    client.post("/command", json={"command": "stand", "params": {}})

    counts = client.get("/journal/counts").json()
    assert counts["transitions"] >= 1
    transitions = client.get("/journal/transitions?limit=5").json()["transitions"]
    assert isinstance(transitions, list)
