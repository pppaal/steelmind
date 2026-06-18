"""Session recorder: capture/skip/cap, the start/stop/status/export API, and
replay of a recorded timeline."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from backend.main.context import AppContext
from backend.models import RobotState, SensorData, SensorEvent, StateTransitionEvent
from backend.recorder import SessionRecorder


def test_recorder_inactive_ignores_events() -> None:
    rec = SessionRecorder()
    rec.capture({"type": "ai_command", "input": "x"})
    assert rec.event_count == 0


def test_recorder_captures_and_skips_sensor() -> None:
    rec = SessionRecorder()
    rec.start()
    rec.capture(SensorEvent(data=SensorData()))  # sensor → skipped
    rec.capture({"type": "ai_command", "input": "wave"})
    rec.capture(StateTransitionEvent(from_state=RobotState.IDLE, to_state=RobotState.STANDING))
    rec.stop()
    exp = rec.export()
    assert exp["count"] == 2
    kinds = [e["event"]["type"] for e in exp["events"]]
    assert "sensor" not in kinds
    assert kinds == ["ai_command", "state_transition"]
    assert all("t" in e for e in exp["events"])


def test_recorder_caps_events() -> None:
    rec = SessionRecorder(max_events=3)
    rec.start()
    for i in range(10):
        rec.capture({"type": "tick", "i": i})
    assert rec.event_count == 3
    assert rec.export()["truncated"] is True


def test_recorder_skips_replayed_frames() -> None:
    rec = SessionRecorder()
    rec.start()
    rec.capture({"type": "status", "replay": True})  # a replayed frame
    rec.capture({"type": "replay_started", "count": 1})  # a replay control frame
    rec.capture({"type": "ai_command", "input": "ok"})
    assert [e["event"]["type"] for e in rec.export()["events"]] == ["ai_command"]


def test_recording_api_round_trip(fresh_app: TestClient) -> None:
    assert fresh_app.get("/recording").json()["active"] is False
    assert fresh_app.post("/recording/start").json()["active"] is True
    # A command produces a state_transition broadcast → captured by the tap.
    fresh_app.post("/command", json={"command": "stand"})
    stopped = fresh_app.post("/recording/stop").json()
    assert stopped["active"] is False
    exp = fresh_app.get("/recording/export").json()
    types = [e["event"]["type"] for e in exp["events"]]
    assert "state_transition" in types
    assert "sensor" not in types  # high-frequency telemetry stays out


@pytest.mark.asyncio
async def test_run_replay_rebroadcasts_tagged_frames() -> None:
    ctx = AppContext()
    ctx.manager.broadcast = AsyncMock()  # capture what gets re-broadcast
    events = [
        {"t": 0.0, "event": {"type": "state_transition", "to_state": "STANDING"}},
        {"t": 0.0, "event": {"type": "ai_command", "input": "wave"}},
    ]
    await ctx._run_replay(events, speed=100.0)
    sent = [c.args[0] for c in ctx.manager.broadcast.call_args_list]
    assert sent[0]["type"] == "replay_started"
    assert sent[-1]["type"] == "replay_complete"
    # The data frames are re-broadcast verbatim but tagged replay=True.
    body = [f for f in sent if f.get("replay")]
    assert [f["type"] for f in body] == ["state_transition", "ai_command"]


def test_replay_empty_is_rejected(fresh_app: TestClient) -> None:
    assert fresh_app.post("/recording/replay", json={}).status_code == 400


def test_replay_api_starts_and_stops(fresh_app: TestClient) -> None:
    events = [{"t": 0.0, "event": {"type": "ai_command", "input": "x"}}]
    r = fresh_app.post("/recording/replay", json={"events": events, "speed": 5})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "count": 1, "speed": 5.0, "replaying": True}
    assert fresh_app.post("/recording/replay/stop").json()["replaying"] is False
