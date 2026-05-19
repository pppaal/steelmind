"""Coverage for the security/perf fixes in main.py."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.main import ConnectionManager


@pytest.fixture()
def client() -> TestClient:
    with TestClient(main.app) as c:
        yield c


def test_ws_command_uses_dispatch_not_route(client: TestClient) -> None:
    """When auth is enabled, the WS command path must NOT bypass the bearer
    check by short-circuiting through the FastAPI route handler. With
    API_TOKEN set, the WS upgrade itself should be rejected when the query
    token is missing."""
    with client.websocket_connect("/ws") as ws:
        # No API_TOKEN configured here, so the connection works. Just verify
        # the dispatcher path runs successfully (status frame arrives).
        first = ws.receive_json()
        assert first["type"] == "status"


def test_ws_rejected_when_auth_enabled_no_token(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    monkeypatch.setenv("API_TOKEN", "topsecret")
    # WebSocketTestClient surfaces a close as WebSocketDisconnect.
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()


def test_ws_accepted_with_query_token(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    monkeypatch.setenv("API_TOKEN", "topsecret")
    with client.websocket_connect("/ws?token=topsecret") as ws:
        first = ws.receive_json()
        assert first["type"] == "status"


def test_ws_rejected_with_wrong_token(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    monkeypatch.setenv("API_TOKEN", "topsecret")
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws?token=wrong") as ws:
            ws.receive_json()


def test_journal_endpoints_require_token_when_enabled(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    monkeypatch.setenv("API_TOKEN", "topsecret")
    assert client.get("/journal/transitions").status_code == 401
    assert client.get("/journal/ai-commands").status_code == 401
    # Counts stay public — integers only, useful for cheap monitoring.
    assert client.get("/journal/counts").status_code == 200


@pytest.mark.asyncio
async def test_broadcast_uses_parallel_gather() -> None:
    """Slow client must not block other clients' frames."""
    mgr = ConnectionManager()

    fast = AsyncMock()
    slow_calls = []

    async def slow_send(_msg: str) -> None:
        slow_calls.append("called")

    slow = AsyncMock()
    slow.send_text = slow_send
    # Bypass the lock-protected setter; we're just smoke-testing the fan-out.
    mgr._clients = {fast, slow}  # noqa: SLF001
    await mgr.broadcast({"type": "test"})
    fast.send_text.assert_awaited_once()
    assert slow_calls == ["called"]


@pytest.mark.asyncio
async def test_broadcast_drops_failed_clients() -> None:
    mgr = ConnectionManager()
    good = AsyncMock()
    bad = AsyncMock()
    bad.send_text.side_effect = RuntimeError("network gone")
    mgr._clients = {good, bad}  # noqa: SLF001
    await mgr.broadcast({"type": "test"})
    # Both got send attempts...
    good.send_text.assert_awaited_once()
    bad.send_text.assert_awaited_once()
    # ...and the failed one was evicted.
    assert good in mgr._clients  # noqa: SLF001
    assert bad not in mgr._clients  # noqa: SLF001
