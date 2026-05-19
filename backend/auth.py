from __future__ import annotations

import os
import secrets

from fastapi import HTTPException, Request, WebSocket


def _current_token() -> str:
    return os.getenv("API_TOKEN", "").strip()


def auth_enabled() -> bool:
    return bool(_current_token())


def require_token(request: Request) -> None:
    """FastAPI dependency. No-op when API_TOKEN is unset (dev/demo); otherwise
    requires a matching `Authorization: Bearer <token>` header. Reads the env
    var on every call so test fixtures and live config changes take effect
    without an import-time snapshot."""
    token_expected = _current_token()
    if not token_expected:
        return
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = header.split(" ", 1)[1].strip()
    if not secrets.compare_digest(token, token_expected):
        raise HTTPException(status_code=403, detail="invalid token")


async def require_token_ws(ws: WebSocket) -> bool:
    """WebSocket-side equivalent. Returns True if the connection is allowed;
    otherwise closes the socket with 4401 (custom close code) and returns False.

    Token is accepted via the `?token=...` query parameter — browsers can't
    set Authorization headers on WS upgrade requests, so a query parameter is
    the standard alternative."""
    token_expected = _current_token()
    if not token_expected:
        return True
    token = ws.query_params.get("token", "")
    if not token or not secrets.compare_digest(token, token_expected):
        await ws.close(code=4401, reason="invalid or missing token")
        return False
    return True
