"""Session recorder: capture/skip/cap, and the start/stop/status/export API."""

from fastapi.testclient import TestClient

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
