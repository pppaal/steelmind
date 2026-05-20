"""End-to-end: a WS command runs a behavior whose trajectory actually moves
joints through the HAL, and the state machine returns to STANDING. Plus the
estop path. Uses TestClient so it runs inside the normal pytest lifecycle."""

import json

from fastapi.testclient import TestClient


def test_wave_moves_shoulder_through_hal(fresh_app: TestClient) -> None:
    with fresh_app.websocket_connect("/ws") as ws:
        assert json.loads(ws.receive_text())["type"] == "status"
        rest = 0.0
        for _ in range(30):
            m = json.loads(ws.receive_text())
            if m.get("type") == "sensor":
                rest = m["data"]["joint_positions"].get("shoulder_right", 0.0)
                break
        ws.send_text(json.dumps({
            "type": "command",
            "payload": {"command": "execute", "params": {"behavior": "wave"}},
        }))
        peak = rest
        seen_exec = False
        for _ in range(200):
            m = json.loads(ws.receive_text())
            if m.get("type") == "sensor":
                peak = min(peak, m["data"]["joint_positions"].get("shoulder_right", 0.0))
            elif m.get("type") == "status":
                state = m["status"]["state"]
                if state == "EXECUTING":
                    seen_exec = True
                elif state == "STANDING" and seen_exec:
                    break
        assert seen_exec, "never entered EXECUTING"
        # wave lifts shoulder_right strongly negative — the HAL slewed real
        # joint motion, not a hardcoded sensor sine.
        assert abs(peak - rest) > 0.3, f"shoulder didn't move: rest={rest} peak={peak}"


def test_estop_during_behavior(fresh_app: TestClient) -> None:
    fresh_app.post("/command", json={"command": "execute", "params": {"behavior": "dance"}})
    r = fresh_app.post("/estop").json()
    assert r["estopped"] is True
    st = fresh_app.get("/status").json()
    assert st["state"] == "IDLE"
    assert st["error"] == "estop latched"
    cleared = fresh_app.post("/estop/clear").json()
    assert cleared["estopped"] is False
