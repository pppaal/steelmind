"""AI routine composition. The Anthropic client is faked so the full
endpoint path (compose → strict validation → save → optional run) is tested
without a network call."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from backend.ai_commander import AICommander


def _tool_use_response(steps, explanation="ok"):
    """Mimic an Anthropic Messages response carrying a single tool_use block."""
    block = SimpleNamespace(
        type="tool_use",
        name="build_routine",
        input={"steps": steps, "explanation": explanation},
    )
    return SimpleNamespace(content=[block])


def test_ai_routine_disabled_without_key(fresh_app: TestClient) -> None:
    r = fresh_app.post("/ai-routine", json={"text": "wave then dance", "name": "x"})
    assert r.status_code == 503


def _enable_fake_ai(client: TestClient, steps) -> AsyncMock:
    """Swap the running app's AICommander client for a fake returning `steps`."""
    import backend.main as main

    fake_client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=_tool_use_response(steps))))
    main.ctx.ai._client = fake_client
    return fake_client.messages.create


def test_ai_routine_composes_and_saves(fresh_app: TestClient) -> None:
    steps = [
        {"type": "command", "command": "stand"},
        {"type": "behavior", "behavior": "wave"},
        {"type": "wait", "seconds": 0.1},
        {"type": "command", "command": "idle"},
    ]
    create = _enable_fake_ai(fresh_app, steps)
    r = fresh_app.post("/ai-routine", json={"text": "greet politely", "name": "greet"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "greet"
    assert len(body["steps"]) == 4
    create.assert_awaited()  # AI was actually consulted
    # Saved and listable.
    listing = fresh_app.get("/routines").json()["routines"]
    assert "greet" in listing


def test_ai_routine_rejects_unknown_behavior_then_502(fresh_app: TestClient) -> None:
    # The fake AI returns an invalid behavior twice → endpoint gives up 502.
    _enable_fake_ai(fresh_app, [{"type": "behavior", "behavior": "moonwalk"}])
    r = fresh_app.post("/ai-routine", json={"text": "do the moonwalk", "name": "bad"})
    assert r.status_code == 502


def test_ai_routine_empty_text_400(fresh_app: TestClient) -> None:
    _enable_fake_ai(fresh_app, [{"type": "command", "command": "stand"}])
    r = fresh_app.post("/ai-routine", json={"text": "  ", "name": "x"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_compose_routine_disabled() -> None:
    ai = AICommander(api_key=None)
    from backend.ai_commander import AICommanderError

    with pytest.raises(AICommanderError):
        await ai.compose_routine("x", has_chain=False)


@pytest.mark.asyncio
async def test_compose_routine_parses_tool_use() -> None:
    ai = AICommander(api_key="sk-fake")
    ai._client = SimpleNamespace(
        messages=SimpleNamespace(
            create=AsyncMock(
                return_value=_tool_use_response([{"type": "command", "command": "stand"}], "stand up")
            )
        )
    )
    result = await ai.compose_routine("stand", has_chain=False)
    assert result.explanation == "stand up"
    assert result.steps == [{"type": "command", "command": "stand"}]


_ = sys
