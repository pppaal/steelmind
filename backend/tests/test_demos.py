"""Demonstration capture: recorder logic, LeRobot-style export, and the API
(including real capture through the running sensor loop)."""

import time

from fastapi.testclient import TestClient

from backend.demos import DemoRecorder


def test_records_episodes_with_success_labels() -> None:
    rec = DemoRecorder(fps=10.0)
    rec.capture({"j": 1.0})  # ignored while inactive
    assert rec.status()["episodes"] == 0

    rec.start("pick up cube")
    assert rec.active is True
    rec.capture({"j": 0.0})
    rec.capture({"j": 0.1})
    out = rec.stop(success=True)
    assert out == {"ok": True, "episode_index": 0, "length": 2}
    assert rec.active is False

    rec.start("again")
    rec.capture({"j": 0.5})
    rec.stop(success=False, notes="dropped it")
    meta = rec.episodes()
    assert [e["success"] for e in meta] == [True, False]
    assert [e["task"] for e in meta] == ["pick up cube", "again"]


def test_stop_without_active_is_noop() -> None:
    rec = DemoRecorder(fps=10.0)
    assert rec.stop(success=True)["ok"] is False


def test_frames_truncate_at_cap() -> None:
    rec = DemoRecorder(fps=10.0, max_frames_per_episode=3)
    rec.start()
    for i in range(10):
        rec.capture({"j": float(i)})
    rec.stop(success=True)
    assert rec.episodes()[0]["length"] == 3
    assert rec.episodes()[0]["truncated"] is True


def test_export_is_lerobot_style_with_next_state_action() -> None:
    rec = DemoRecorder(fps=2.0)
    rec.start("t")
    rec.capture({"a": 0.0, "b": 9.0})
    rec.capture({"a": 1.0, "b": 8.0})
    rec.capture({"a": 2.0, "b": 7.0})
    rec.stop(success=True)
    exp = rec.export(["a", "b"])
    assert exp["fps"] == 2.0
    assert exp["features"]["observation.state"]["shape"] == [2]
    assert exp["total_episodes"] == 1 and exp["total_frames"] == 3
    f = exp["frames"]
    # action[i] == state[i+1]; last frame holds and is flagged done.
    assert f[0]["observation.state"] == [0.0, 9.0]
    assert f[0]["action"] == [1.0, 8.0]
    assert f[1]["action"] == [2.0, 7.0]
    assert f[2]["action"] == [2.0, 7.0] and f[2]["next.done"] is True
    assert [fr["timestamp"] for fr in f] == [0.0, 0.5, 1.0]


def test_demos_api_round_trip(fresh_app: TestClient) -> None:
    assert fresh_app.get("/demos").json()["active"] is False
    assert fresh_app.post("/demos/start", json={"task": "wave"}).json()["active"] is True
    # Double start is rejected.
    assert fresh_app.post("/demos/start", json={}).status_code == 409
    # Let the sensor loop capture a few frames against the live hardware.
    time.sleep(0.3)
    stopped = fresh_app.post("/demos/stop", json={"success": True}).json()
    assert stopped["ok"] is True
    assert stopped["episodes"] == 1
    exp = fresh_app.get("/demos/export").json()
    assert exp["total_episodes"] == 1
    assert exp["frames"], "expected captured frames from the sensor loop"
    assert exp["episodes"][0]["success"] is True
    # The state vector matches the robot's joint count.
    dim = exp["features"]["observation.state"]["shape"][0]
    assert len(exp["frames"][0]["observation.state"]) == dim


def test_demos_stop_without_start_409(fresh_app: TestClient) -> None:
    assert fresh_app.post("/demos/stop", json={"success": True}).status_code == 409
