"""Command signing helpers and the WS replay-protection enforcement."""

import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.signing import NonceCache, canonical, sign, verify

_TOKEN = "operator-secret"


def test_sign_verify_round_trip() -> None:
    sig = sign(_TOKEN, "stand", {"behavior": "wave"}, 100.0, "n1")
    assert verify(_TOKEN, sig, "stand", {"behavior": "wave"}, 100.0, "n1")
    # Wrong key, tampered command/params/ts/nonce all fail.
    assert not verify("other", sig, "stand", {"behavior": "wave"}, 100.0, "n1")
    assert not verify(_TOKEN, sig, "walk", {"behavior": "wave"}, 100.0, "n1")
    assert not verify(_TOKEN, sig, "stand", {"behavior": "x"}, 100.0, "n1")
    assert not verify(_TOKEN, sig, "stand", {"behavior": "wave"}, 101.0, "n1")


def test_canonical_is_param_order_independent() -> None:
    a = canonical("c", {"x": 1, "y": 2}, 1.0, "n")
    b = canonical("c", {"y": 2, "x": 1}, 1.0, "n")
    assert a == b


def test_nonce_cache_detects_reuse_and_bounds() -> None:
    cache = NonceCache(capacity=3)
    assert cache.seen("a") is False
    assert cache.seen("a") is True  # second time → seen
    cache.seen("b")
    cache.seen("c")
    cache.seen("d")  # evicts "a" (oldest)
    assert cache.seen("a") is False  # "a" was evicted → treated as fresh


def _signed(command: str, params: dict | None = None, *, ts=None, nonce=None, token=_TOKEN):
    ts = time.time() if ts is None else ts
    nonce = nonce or uuid.uuid4().hex
    params = params or {}
    return {
        "type": "command",
        "payload": {"command": command, "params": params},
        "ts": ts,
        "nonce": nonce,
        "sig": sign(token, command, params, ts, nonce),
    }


@pytest.fixture()
def signed_app(app_booter):
    with app_booter(API_TOKEN=_TOKEN, REQUIRE_SIGNED_COMMANDS="1") as client:
        yield client


def _find(ws, pred, *, limit=15):
    # The socket also receives broadcasts (status / state_transition), so scan
    # frames for the one we care about rather than assuming ordering.
    for _ in range(limit):
        m = json.loads(ws.receive_text())
        if pred(m):
            return m
    raise AssertionError("expected frame not seen")


def _is_cmd_response(m: dict) -> bool:
    return "ok" in m and "status" in m and m.get("type") != "error"


def _is_error(m: dict) -> bool:
    return m.get("type") == "error"


def test_ws_accepts_a_properly_signed_command(signed_app: TestClient) -> None:
    with signed_app.websocket_connect(f"/ws?token={_TOKEN}") as ws:
        ws.send_text(json.dumps(_signed("stand")))
        assert _find(ws, _is_cmd_response)["ok"] is True


def test_ws_rejects_unsigned_command_when_required(signed_app: TestClient) -> None:
    with signed_app.websocket_connect(f"/ws?token={_TOKEN}") as ws:
        ws.send_text(json.dumps({"type": "command", "payload": {"command": "stand"}}))
        assert "signature required" in _find(ws, _is_error)["detail"]


def test_ws_rejects_replayed_command(signed_app: TestClient) -> None:
    with signed_app.websocket_connect(f"/ws?token={_TOKEN}") as ws:
        frame = _signed("stand")
        ws.send_text(json.dumps(frame))
        assert _find(ws, _is_cmd_response)["ok"] is True
        ws.send_text(json.dumps(frame))  # same nonce → replay
        assert "replay" in _find(ws, _is_error)["detail"]


def test_ws_rejects_stale_and_bad_signature(signed_app: TestClient) -> None:
    with signed_app.websocket_connect(f"/ws?token={_TOKEN}") as ws:
        ws.send_text(json.dumps(_signed("stand", ts=time.time() - 10_000)))
        assert "skew" in _find(ws, _is_error)["detail"]
        bad = _signed("stand")
        bad["sig"] = "deadbeef"
        ws.send_text(json.dumps(bad))
        assert "invalid command signature" in _find(ws, _is_error)["detail"]
