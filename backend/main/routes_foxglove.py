"""Foxglove WebSocket bridge (foxglove.websocket.v1).

Speaks just enough of the protocol for Foxglove Studio to connect to
`/foxglove`, discover steelmind's telemetry channels, and stream them live —
so the whole Foxglove panel ecosystem (3D, plots, raw messages) works without
building our own. JSON encoding; channels carry the same payloads the console
sees over /ws. Read-only (viewer)."""

from __future__ import annotations

import asyncio
import json
import struct
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..auth import Role, require_token_ws
from .context import ctx

router = APIRouter()

_SUBPROTOCOL = "foxglove.websocket.v1"
_OPCODE_MESSAGE_DATA = 0x01
_LOOSE_OBJECT = json.dumps({"type": "object", "additionalProperties": True})

# Advertised channels: (id, topic, schemaName). Event "type" → channel id.
_CHANNELS = [
    {"id": 1, "topic": "/status", "schemaName": "steelmind/Status"},
    {"id": 2, "topic": "/sensor", "schemaName": "steelmind/Sensor"},
    {"id": 3, "topic": "/state_transition", "schemaName": "steelmind/Transition"},
    {"id": 4, "topic": "/events", "schemaName": "steelmind/Event"},
]
_TYPE_TO_CHANNEL = {"status": 1, "sensor": 2, "state_transition": 3}


def _advertise_payload() -> dict:
    return {
        "op": "advertise",
        "channels": [
            {
                "id": c["id"],
                "topic": c["topic"],
                "encoding": "json",
                "schemaName": c["schemaName"],
                "schema": _LOOSE_OBJECT,
                "schemaEncoding": "jsonschema",
            }
            for c in _CHANNELS
        ],
    }


def _data_frame(subscription_id: int, payload: dict) -> bytes:
    """Foxglove binary MessageData: opcode | subId(u32 LE) | ts_ns(u64 LE) | json."""
    header = bytes([_OPCODE_MESSAGE_DATA]) + struct.pack("<IQ", subscription_id, time.time_ns())
    return header + json.dumps(payload, default=str).encode("utf-8")


@router.websocket("/foxglove")
async def foxglove_ws(ws: WebSocket) -> None:
    await ws.accept(subprotocol=_SUBPROTOCOL)
    if await require_token_ws(ws, min_role=Role.VIEWER) is None:
        return
    await ws.send_text(json.dumps({
        "op": "serverInfo",
        "name": "steelmind",
        "capabilities": [],
        "supportedEncodings": ["json"],
        "metadata": {},
    }))
    await ws.send_text(json.dumps(_advertise_payload()))

    # subscription_id -> channel_id (set by the client's "subscribe" ops)
    subs: dict[int, int] = {}
    queue = ctx.manager.subscribe()

    async def _recv() -> None:
        while True:
            msg = json.loads(await ws.receive_text())
            op = msg.get("op")
            if op == "subscribe":
                for s in msg.get("subscriptions", []):
                    subs[int(s["id"])] = int(s["channelId"])
            elif op == "unsubscribe":
                for sid in msg.get("subscriptionIds", []):
                    subs.pop(int(sid), None)

    async def _send() -> None:
        while True:
            payload = await queue.get()
            channel_id = _TYPE_TO_CHANNEL.get(payload.get("type"), 4)
            for sub_id, ch in subs.items():
                if ch == channel_id:
                    await ws.send_bytes(_data_frame(sub_id, payload))

    try:
        await asyncio.gather(_recv(), _send())
    except WebSocketDisconnect:
        pass
    finally:
        ctx.manager.unsubscribe(queue)
