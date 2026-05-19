import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def auth_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("API_TOKEN", "s3cret")
    # require_token re-reads the env var on each call, so no reload needed.
    from backend import main

    return TestClient(main.app)


def test_command_rejects_missing_token(auth_client: TestClient) -> None:
    r = auth_client.post("/command", json={"command": "stand", "params": {}})
    assert r.status_code == 401


def test_command_rejects_wrong_token(auth_client: TestClient) -> None:
    r = auth_client.post(
        "/command",
        json={"command": "stand", "params": {}},
        headers={"Authorization": "Bearer wrong"},
    )
    assert r.status_code == 403


def test_command_accepts_correct_token(auth_client: TestClient) -> None:
    r = auth_client.post(
        "/command",
        json={"command": "stand", "params": {}},
        headers={"Authorization": "Bearer s3cret"},
    )
    assert r.status_code == 200


def test_health_works_without_token(auth_client: TestClient) -> None:
    body = auth_client.get("/health").json()
    assert body["auth_required"] is True
