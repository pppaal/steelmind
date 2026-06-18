"""Keyframe store + teach-and-repeat endpoints."""

import pytest
from fastapi.testclient import TestClient

from backend.keyframes import KeyframeStore


@pytest.mark.asyncio
async def test_record_persist_reload(tmp_path) -> None:
    path = tmp_path / "kf.json"
    s1 = KeyframeStore(path)
    await s1.record("home", {"a": 0.0, "b": 0.0})
    await s1.record("up", {"a": 1.0, "b": -0.5})
    s2 = KeyframeStore(path)
    await s2.load()
    assert set(s2.names) == {"home", "up"}
    assert s2.get("up") == {"a": 1.0, "b": -0.5}


@pytest.mark.asyncio
async def test_delete(tmp_path) -> None:
    s = KeyframeStore(tmp_path / "kf.json")
    await s.record("x", {"a": 1.0})
    assert await s.delete("x") is True
    assert await s.delete("x") is False
    assert s.names == []


@pytest.mark.asyncio
async def test_build_trajectory_through_frames(tmp_path) -> None:
    s = KeyframeStore(tmp_path / "kf.json")
    await s.record("a", {"j": 0.0})
    await s.record("b", {"j": 1.0})
    traj = s.build_trajectory(["a", "b"], segment_duration=1.0, start_pose={"j": 0.0})
    # 1 segment start→a (j stays 0), 1 segment a→b (0→1), + 0.3 hold.
    assert abs(traj.duration - 2.3) < 1e-6
    # At the very end the joint should hold at b's pose.
    assert abs(traj.sample(traj.duration)["j"] - 1.0) < 1e-6


@pytest.mark.asyncio
async def test_build_trajectory_unknown_frame_raises(tmp_path) -> None:
    s = KeyframeStore(tmp_path / "kf.json")
    await s.record("a", {"j": 0.0})
    with pytest.raises(KeyError):
        s.build_trajectory(["a", "ghost"], segment_duration=1.0)


def test_record_and_play_via_api(fresh_app: TestClient) -> None:
    # Record two keyframes from current pose (sim starts at zeros).
    r1 = fresh_app.post("/keyframes/home")
    assert r1.status_code == 200
    assert "pose" in r1.json()
    # Jog a joint then record a second frame.
    fresh_app.post("/jog", json={"joint": "shoulder_right", "delta": 0.2})
    r2 = fresh_app.post("/keyframes/raised")
    assert r2.status_code == 200

    listing = fresh_app.get("/keyframes").json()["keyframes"]
    assert {"home", "raised"} <= set(listing)

    play = fresh_app.post("/keyframes/play", json={"names": ["home", "raised"]})
    assert play.status_code == 200
    assert play.json()["duration"] > 0


def test_play_unknown_keyframe_400(fresh_app: TestClient) -> None:
    r = fresh_app.post("/keyframes/play", json={"names": ["nope"]})
    assert r.status_code == 400


def test_delete_keyframe_api(fresh_app: TestClient) -> None:
    fresh_app.post("/keyframes/temp")
    assert fresh_app.delete("/keyframes/temp").status_code == 200
    assert fresh_app.delete("/keyframes/temp").status_code == 404


def test_record_rejects_invalid_name(fresh_app: TestClient) -> None:
    # Over-length and illegal-character names are refused with 400 before any
    # store write (slashes are caught by routing as 404/405).
    assert fresh_app.post("/keyframes/" + "a" * 65).status_code == 400
    assert fresh_app.post("/keyframes/bad!name").status_code == 400
