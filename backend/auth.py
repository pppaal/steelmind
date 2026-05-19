from __future__ import annotations

import os
import secrets

from fastapi import HTTPException, Request


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
