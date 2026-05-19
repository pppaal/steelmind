"""Coverage for role-based auth: viewer/operator/admin separation."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def roles_app(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("API_TOKEN_VIEWER", "viewer-tok")
    monkeypatch.setenv("API_TOKEN_OPERATOR", "operator-tok")
    monkeypatch.setenv("API_TOKEN_ADMIN", "admin-tok")
    import importlib
    import sys

    for name in list(sys.modules):
        if name == "backend.main" or name.startswith("backend.main."):
            del sys.modules[name]
    main = importlib.import_module("backend.main")
    with TestClient(main.app) as c:
        yield c


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def test_viewer_can_read_journal_but_not_command(roles_app: TestClient) -> None:
    assert roles_app.get("/journal/transitions", headers=_h("viewer-tok")).status_code == 200
    r = roles_app.post("/command", json={"command": "stand"}, headers=_h("viewer-tok"))
    assert r.status_code == 403


def test_operator_can_command_but_not_admin_reset(roles_app: TestClient) -> None:
    assert (
        roles_app.post("/command", json={"command": "stand"}, headers=_h("operator-tok")).status_code
        == 200
    )
    assert roles_app.post("/ai-reset", headers=_h("operator-tok")).status_code == 403


def test_admin_can_do_everything(roles_app: TestClient) -> None:
    h = _h("admin-tok")
    assert roles_app.get("/journal/transitions", headers=h).status_code == 200
    assert roles_app.post("/command", json={"command": "stand"}, headers=h).status_code == 200
    assert roles_app.post("/ai-reset", headers=h).status_code == 200


def test_unknown_token_rejected(roles_app: TestClient) -> None:
    assert roles_app.get(
        "/journal/transitions", headers=_h("nope")
    ).status_code == 403


def test_missing_token_rejected(roles_app: TestClient) -> None:
    assert roles_app.get("/journal/transitions").status_code == 401


def test_legacy_api_token_grants_operator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_TOKEN", "legacy-tok")
    import importlib
    import sys

    for name in list(sys.modules):
        if name == "backend.main" or name.startswith("backend.main."):
            del sys.modules[name]
    main = importlib.import_module("backend.main")
    with TestClient(main.app) as c:
        # legacy can issue commands (operator)…
        assert c.post("/command", json={"command": "stand"}, headers=_h("legacy-tok")).status_code == 200
        # …but cannot run admin-only ops.
        assert c.post("/ai-reset", headers=_h("legacy-tok")).status_code == 403
