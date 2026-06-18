"""The /ws WebSocket endpoint and its message handler."""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from ..auth import Role, auth_enabled, require_token_ws
from ..models import CommandRequest, StatusEvent
from ..signing import NonceCache, verify
from .config import COMMAND_SKEW_SEC, REQUIRE_SIGNED_COMMANDS
from .context import ctx, require_deadman
from .motion import _dispatch_command

router = APIRouter()

# Recently-seen command nonces (process-wide) for replay rejection.
_nonces = NonceCache()


def _signature_error(token: str, msg: dict) -> str | None:
    """Validate a command's (ts, nonce, sig) when signing is enforced. Returns
    an error string to reject with, or None when the command is acceptable.
    A no-op unless REQUIRE_SIGNED_COMMANDS and auth (a per-connection key) are
    both in effect."""
    if not (REQUIRE_SIGNED_COMMANDS and auth_enabled() and token):
        return None
    ts, nonce, sig = msg.get("ts"), msg.get("nonce"), msg.get("sig")
    if not isinstance(ts, (int, float)) or not nonce or not sig:
        return "command signature required (ts, nonce, sig)"
    if abs(time.time() - ts) > COMMAND_SKEW_SEC:
        return "command timestamp outside allowed skew"
    payload = msg.get("payload", {}) or {}
    command = payload.get("command", "")
    params = payload.get("params", {}) or {}
    # Pass ts through verbatim (no float() recast) so the canonical string
    # matches the client byte-for-byte regardless of int/float formatting.
    if not verify(token, str(sig), command, params, ts, str(nonce)):
        return "invalid command signature"
    # Only consume a nonce once the signature is authentic, so a bad frame
    # can't burn (or pre-seed) a nonce.
    if _nonces.seen(str(nonce)):
        return "replay detected (nonce reused)"
    return None


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    # Accept the upgrade first so we can send a structured close on auth fail.
    await ws.accept()
    role = await require_token_ws(ws, min_role=Role.OPERATOR)
    if role is None:
        return
    token = ws.query_params.get("token", "")
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
            await _handle_ws_message(ws, msg, token)
    except WebSocketDisconnect:
        pass
    finally:
        ctx.ws_last_seen.pop(ws, None)
        await ctx.manager.disconnect(ws)


async def _handle_ws_message(ws: WebSocket, msg: dict, token: str = "") -> None:
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
        sig_err = _signature_error(token, msg)
        if sig_err:
            await ws.send_text(json.dumps({"type": "error", "detail": sig_err}))
            return
        try:
            require_deadman()
            req = CommandRequest(**msg.get("payload", {}))
            resp = await _dispatch_command(req)
            await ws.send_text(resp.model_dump_json())
        except HTTPException as e:
            await ws.send_text(json.dumps({"type": "error", "detail": e.detail}))
    else:
        await ws.send_text(json.dumps({"type": "error", "detail": f"unknown message: {kind}"}))
