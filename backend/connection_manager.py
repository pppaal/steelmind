from __future__ import annotations

import asyncio
import json

from fastapi import WebSocket
from pydantic import BaseModel


class ConnectionManager:
    """Tracks connected WebSocket clients and fans out broadcasts to them."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        await self.attach(ws)

    async def attach(self, ws: WebSocket) -> None:
        """Register an already-accepted socket. Used by the auth-gated /ws
        endpoint where accept() must run before the token check."""
        async with self._lock:
            self._clients.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, payload: BaseModel | dict) -> None:
        if isinstance(payload, BaseModel):
            message = payload.model_dump_json()
        else:
            message = json.dumps(payload, default=str)
        async with self._lock:
            targets = list(self._clients)
        if not targets:
            return
        # Fan out in parallel so one slow client doesn't delay the broadcast
        # cadence for everyone else. Failures are collected and the dead
        # sockets removed after the send wave completes. Re-raise
        # CancelledError so shutdown isn't masked by a stuck client.
        results = await asyncio.gather(
            *(ws.send_text(message) for ws in targets), return_exceptions=True
        )
        for ws, result in zip(targets, results, strict=True):
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, Exception):
                await self.disconnect(ws)

    @property
    def count(self) -> int:
        return len(self._clients)
