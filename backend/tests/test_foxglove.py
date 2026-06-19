"""Foxglove WebSocket bridge: handshake, channel advertisement, and a live
binary MessageData frame."""

import json
import struct

from fastapi.testclient import TestClient


def test_handshake_advertises_channels(fresh_app: TestClient) -> None:
    with fresh_app.websocket_connect("/foxglove", subprotocols=["foxglove.websocket.v1"]) as ws:
        info = json.loads(ws.receive_text())
        assert info["op"] == "serverInfo"
        assert "json" in info["supportedEncodings"]
        adv = json.loads(ws.receive_text())
        assert adv["op"] == "advertise"
        topics = {c["topic"] for c in adv["channels"]}
        assert {"/status", "/sensor", "/state_transition", "/events"} <= topics
        assert all(c["encoding"] == "json" for c in adv["channels"])


def test_streams_sensor_message_data(fresh_app: TestClient) -> None:
    with fresh_app.websocket_connect("/foxglove", subprotocols=["foxglove.websocket.v1"]) as ws:
        json.loads(ws.receive_text())  # serverInfo
        adv = json.loads(ws.receive_text())  # advertise
        sensor_ch = next(c["id"] for c in adv["channels"] if c["topic"] == "/sensor")
        # Subscribe to the sensor channel (always streaming at SENSOR_HZ).
        ws.send_text(json.dumps({"op": "subscribe", "subscriptions": [{"id": 7, "channelId": sensor_ch}]}))
        raw = ws.receive_bytes()
        assert raw[0] == 0x01  # MessageData opcode
        sub_id, _ts = struct.unpack("<IQ", raw[1:13])
        assert sub_id == 7
        payload = json.loads(raw[13:])
        assert payload["type"] == "sensor"
        assert "joint_positions" in payload["data"]
