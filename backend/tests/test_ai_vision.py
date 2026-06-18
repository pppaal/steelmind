"""Vision grounding: a camera frame passed to AICommander.translate is sent
to the model as an image block, and /ai-command?use_vision wires it up."""

import importlib
import os
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from backend.ai_commander import AICommander
from backend.models import RobotStatus


def _plan_response(steps=None, explanation="ok"):
    block = SimpleNamespace(
        type="tool_use",
        name="execute_robot_plan",
        input={"steps": steps or [{"command": "stand"}], "explanation": explanation},
    )
    return SimpleNamespace(content=[block])


@pytest.mark.asyncio
async def test_translate_includes_image_block() -> None:
    ai = AICommander(api_key="x")
    create = AsyncMock(return_value=_plan_response())
    ai._client = SimpleNamespace(messages=SimpleNamespace(create=create))

    await ai.translate(
        "stand up", RobotStatus(), image=("image/png", "QkExeA==")
    )

    messages = create.call_args.kwargs["messages"]
    content = messages[-1]["content"]
    assert isinstance(content, list)
    img = next(b for b in content if b["type"] == "image")
    assert img["source"]["media_type"] == "image/png"
    assert img["source"]["data"] == "QkExeA=="
    # The text block is still present alongside the image.
    assert any(b["type"] == "text" for b in content)


@pytest.mark.asyncio
async def test_translate_without_image_keeps_text_content() -> None:
    ai = AICommander(api_key="x")
    create = AsyncMock(return_value=_plan_response())
    ai._client = SimpleNamespace(messages=SimpleNamespace(create=create))
    await ai.translate("stand up", RobotStatus())
    # No image → content stays a plain string (unchanged legacy shape).
    assert isinstance(create.call_args.kwargs["messages"][-1]["content"], str)


@pytest.fixture()
def vision_app(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    fd, db = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setenv("JOURNAL_DB", db)
    for var in ("CALIBRATION_FILE", "KEYFRAMES_FILE", "ROUTINES_FILE"):
        f, p = tempfile.mkstemp(suffix=".json")
        os.close(f)
        os.unlink(p)
        monkeypatch.setenv(var, p)
    monkeypatch.setenv("CAMERA", "mock")
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


def test_ai_command_use_vision_attaches_frame(vision_app: TestClient) -> None:
    import backend.main as main

    create = AsyncMock(return_value=_plan_response())
    main.ctx.ai._client = SimpleNamespace(messages=SimpleNamespace(create=create))

    r = vision_app.post("/ai-command", json={"text": "stand", "use_vision": True})
    assert r.status_code == 200
    content = create.call_args.kwargs["messages"][-1]["content"]
    img = next(b for b in content if b["type"] == "image")
    assert img["source"]["media_type"] == "image/png"
