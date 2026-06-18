"""The /ws WebSocket endpoint and its message handler."""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from ..auth import Role, require_token_ws
from ..models import CommandRequest, StatusEvent
from .context import ctx, require_deadman
from .motion import _dispatch_command

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    # Accept the upgrade first so we can send a structured close on auth fail.
    await ws.accept()
    role = await require_token_ws(ws, min_role=Role.OPERATOR)
    if role is None:
        return
    # require_token_ws didn't close → connection is authorized. Register
    # without re-accepting.
    await ctx.manager.attach(ws)
    ctx.ws_last_seen[ws] = time.monotonic()
    try:
        await ws.send_text(StatusEvent(status=ctx.state_machine.status).model_dump_json())
        while True:
            raw = await ws.receive_text()
            ctx.ws_last_seen[ws] = time.monotonic()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_text(json.dumps({"type": "error", "detail": "invalid json"}))
                continue
            await _handle_ws_message(ws, msg)
    except WebSocketDisconnect:
        pass
    finally:
        ctx.ws_last_seen.pop(ws, None)
        await ctx.manager.disconnect(ws)


async def _handle_ws_message(ws: WebSocket, msg: dict) -> None:
    kind = msg.get("type")
    if kind == "ping":
        await ws.send_text(json.dumps({"type": "pong"}))
    elif kind == "pong":
        # Client-side heartbeat echo. last_seen is already updated by the
        # outer receive loop, so we don't need to send anything back.
        return
    elif kind == "deadman":
        # Hold-to-enable ping: the operator is actively holding the enable
        # control. Refreshes the deadman deadline so motion stays permitted.
        ctx.refresh_deadman()
        return
    elif kind == "command":
        try:
            require_deadman()
            req = CommandRequest(**msg.get("payload", {}))
            resp = await _dispatch_command(req)
            await ws.send_text(resp.model_dump_json())
        except HTTPException as e:
            await ws.send_text(json.dumps({"type": "error", "detail": e.detail}))
    else:
        await ws.send_text(json.dumps({"type": "error", "detail": f"unknown message: {kind}"}))
