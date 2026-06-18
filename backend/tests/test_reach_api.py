"""/fk and /reach endpoints. The default sim config has no chain (→ 400);
the shared `so100_app` fixture (conftest) boots the SO-100 config to exercise
the real IK→trajectory path."""

from fastapi.testclient import TestClient


def test_reach_without_chain_returns_400(fresh_app: TestClient) -> None:
    # sim_humanoid (the fresh_app default) ships no kinematic chain.
    assert fresh_app.post("/reach", json={"x": 0.1, "y": 0.1}).status_code == 400
    assert fresh_app.get("/fk").status_code == 400


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


def test_workspace_without_chain_returns_400(fresh_app: TestClient) -> None:
    assert fresh_app.get("/workspace").status_code == 400


def test_workspace_reports_envelope(so100_app: TestClient) -> None:
    body = so100_app.get("/workspace").json()
    assert set(body) >= {"base", "reach", "inner_radius", "outer_radius"}
    assert 0.0 <= body["inner_radius"] <= body["outer_radius"] <= body["reach"] + 1e-9
    # A reachable target sits inside the annulus; a far one is outside it.
    assert body["outer_radius"] < 5.0
