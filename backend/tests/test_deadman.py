"""Deadman / hold-to-enable: motion is gated on an active hold and frozen if
the hold lapses. Off by default, so these tests force DEADMAN_REQUIRED on."""

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from backend.hardware.base import JointSpec
from backend.hardware.mock import MockHardware
from backend.main import context as ctxmod
from backend.main.context import AppContext


def test_deadman_not_required_is_always_ok(monkeypatch) -> None:
    monkeypatch.setattr(ctxmod, "DEADMAN_REQUIRED", False)
    assert AppContext().deadman_ok() is True


def test_deadman_required_blocks_until_held(monkeypatch) -> None:
    monkeypatch.setattr(ctxmod, "DEADMAN_REQUIRED", True)
    monkeypatch.setattr(ctxmod, "DEADMAN_TIMEOUT_SEC", 10.0)
    c = AppContext()
    assert c.deadman_ok() is False
    c.refresh_deadman()
    assert c.deadman_ok() is True


def test_deadman_expires(monkeypatch) -> None:
    monkeypatch.setattr(ctxmod, "DEADMAN_REQUIRED", True)
    monkeypatch.setattr(ctxmod, "DEADMAN_TIMEOUT_SEC", 0.05)
    c = AppContext()
    c.refresh_deadman()
    assert c.deadman_ok() is True
    time.sleep(0.07)
    assert c.deadman_ok() is False


@pytest.mark.asyncio
async def test_release_freezes_active_motion(monkeypatch) -> None:
    monkeypatch.setattr(ctxmod, "DEADMAN_REQUIRED", True)
    monkeypatch.setattr(ctxmod, "DEADMAN_TIMEOUT_SEC", 10.0)
    c = AppContext()
    c.joints = [JointSpec(name="j1", hardware_id="1", lower_limit=-1.0, upper_limit=1.0)]
    c.hardware = MockHardware(c.joints)
    await c.hardware.init()

    async def _spin() -> None:
        while True:
            await asyncio.sleep(0.01)

    # Deadman not held → an active motion is cancelled (frozen).
    c.current_behavior_task = asyncio.create_task(_spin())
    await asyncio.sleep(0)
    await c._check_deadman()
    await asyncio.sleep(0.01)
    assert c.current_behavior_task.done()
    assert c.metrics.deadman_stops_total == 1

    # While held, a running motion is left alone.
    c.refresh_deadman()
    c.current_behavior_task = asyncio.create_task(_spin())
    await asyncio.sleep(0)
    await c._check_deadman()
    assert not c.current_behavior_task.done()
    c.current_behavior_task.cancel()


def test_jog_blocked_without_deadman(fresh_app: TestClient, monkeypatch) -> None:
    import backend.main as main

    monkeypatch.setattr(main.context, "DEADMAN_REQUIRED", True)
    r = fresh_app.post("/jog", json={"joint": "hip_left", "delta": 0.1})
    assert r.status_code == 423


def test_jog_allowed_when_deadman_held(fresh_app: TestClient, monkeypatch) -> None:
    import backend.main as main

    monkeypatch.setattr(main.context, "DEADMAN_REQUIRED", True)
    monkeypatch.setattr(main.context, "DEADMAN_TIMEOUT_SEC", 10.0)
    main.ctx.refresh_deadman()
    r = fresh_app.post("/jog", json={"joint": "hip_left", "delta": 0.1})
    assert r.status_code == 200


def test_ws_deadman_message_arms_commands(fresh_app: TestClient, monkeypatch) -> None:
    import backend.main as main

    monkeypatch.setattr(main.context, "DEADMAN_REQUIRED", True)
    monkeypatch.setattr(main.context, "DEADMAN_TIMEOUT_SEC", 10.0)
    with fresh_app.websocket_connect("/ws") as ws:
        assert json.loads(ws.receive_text())["type"] == "status"
        # Without a hold, a command is rejected with an error frame.
        ws.send_text(json.dumps({"type": "command", "payload": {"command": "stand"}}))
        err = _next_of_type(ws, "error")
        assert "deadman" in err["detail"].lower()
        # Hold the enable control, then the command is accepted.
        ws.send_text(json.dumps({"type": "deadman"}))
        ws.send_text(json.dumps({"type": "command", "payload": {"command": "stand"}}))
        # A CommandResponse (has "status") arrives rather than an error.
        assert _next_command_response(ws)["status"]["state"] in ("STANDING", "IDLE")


def _next_of_type(ws, kind: str, limit: int = 50) -> dict:
    for _ in range(limit):
        m = json.loads(ws.receive_text())
        if m.get("type") == kind:
            return m
    raise AssertionError(f"no {kind} frame")


def _next_command_response(ws, limit: int = 50) -> dict:
    for _ in range(limit):
        m = json.loads(ws.receive_text())
        if "status" in m and m.get("type") != "status":
            return m
        if m.get("type") == "error":
            raise AssertionError(f"unexpected error: {m}")
    raise AssertionError("no command response")
