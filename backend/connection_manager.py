from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

from fastapi import WebSocket
from pydantic import BaseModel


class ConnectionManager:
    """Tracks connected WebSocket clients and fans out broadcasts to them."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        # Optional synchronous observer of every broadcast payload (e.g. the
        # session recorder). Set by the app; runs regardless of client count.
        self.tap: Callable[[BaseModel | dict], None] | None = None
        # Async fan-out queues for secondary consumers (e.g. the Foxglove
        # bridge) that want every payload as a dict without being a /ws client.
        self._subscribers: list[asyncio.Queue[dict]] = []

    def subscribe(self) -> asyncio.Queue[dict]:
        q: asyncio.Queue[dict] = asyncio.Queue(maxsize=512)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict]) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

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
        # Feed the tap first so events are recorded even with no clients
        # connected. The tap must be cheap and must not raise into the loop.
        if self.tap is not None:
            try:
                self.tap(payload)
            except Exception:
                pass
        if isinstance(payload, BaseModel):
            message = payload.model_dump_json()
        else:
            message = json.dumps(payload, default=str)
        # Fan out a dict form to async subscribers (drop on a full/slow queue).
        if self._subscribers:
            as_dict = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
            for q in self._subscribers:
                try:
                    q.put_nowait(as_dict)
                except asyncio.QueueFull:
                    pass
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
