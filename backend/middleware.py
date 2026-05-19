from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

logger = logging.getLogger("steelmind.http")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Generate or propagate an X-Request-Id header and stash it on
    request.state so handlers and loggers can attach it. Also emits one
    structured access log per request with status code and latency."""

    HEADER = "x-request-id"

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get(self.HEADER)
        rid = incoming if incoming else uuid.uuid4().hex
        request.state.request_id = rid
        started = time.monotonic()

        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.monotonic() - started) * 1000
            logger.exception(
                "request failed",
                extra={
                    "request_id": rid,
                    "method": request.method,
                    "path": request.url.path,
                    "elapsed_ms": round(elapsed_ms, 2),
                },
            )
            raise

        response.headers[self.HEADER] = rid
        elapsed_ms = (time.monotonic() - started) * 1000
        logger.info(
            "request",
            extra={
                "request_id": rid,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "elapsed_ms": round(elapsed_ms, 2),
            },
        )
        return response


class RequestSizeLimitMiddleware:
    """Reject POST/PUT/PATCH bodies larger than max_bytes with 413.

    Implemented as a pure ASGI middleware (rather than BaseHTTPMiddleware)
    so the rejection happens before Starlette tries to buffer the body."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "GET")
        if method not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return

        # Cheap pre-check: trust Content-Length when present. (Chunked
        # uploads without a Content-Length are rare in our API surface and
        # would be caught at the per-message limit instead.)
        content_length = self._content_length(scope)
        if content_length is not None and content_length > self.max_bytes:
            await self._send_413(send)
            return

        # Streaming check: enforce the limit as the body actually arrives,
        # so a missing/lying Content-Length can't get past us.
        bytes_seen = 0
        too_large = False

        async def limited_receive() -> dict:
            nonlocal bytes_seen, too_large
            message = await receive()
            if message["type"] == "http.request":
                bytes_seen += len(message.get("body") or b"")
                if bytes_seen > self.max_bytes:
                    too_large = True
            return message

        # Wrap receive so the app sees a truncated stream and aborts cleanly.
        async def gated_receive() -> dict:
            if too_large:
                # Pretend the connection ended; the app will return early.
                return {"type": "http.disconnect"}
            return await limited_receive()

        completed = False

        async def intercepting_send(message: dict) -> None:
            nonlocal completed
            if too_large and not completed:
                completed = True
                await self._send_413(send)
                return
            await send(message)

        await self.app(scope, gated_receive, intercepting_send)
        if too_large and not completed:
            await self._send_413(send)

    @staticmethod
    def _content_length(scope: dict) -> int | None:
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    return int(value)
                except ValueError:
                    return None
        return None

    @staticmethod
    async def _send_413(send: Callable) -> None:
        body = b'{"detail":"request body too large"}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
