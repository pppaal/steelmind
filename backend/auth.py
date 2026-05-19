from __future__ import annotations

import secrets
from enum import IntEnum

from fastapi import HTTPException, Request, WebSocket

from .secrets import env_or_file


class Role(IntEnum):
    """Role lattice. Higher integer ⇒ strictly more privilege.

    A token granted a given role implicitly satisfies any requirement at or
    below it (admin satisfies operator, operator satisfies viewer)."""

    NONE = 0
    VIEWER = 1
    OPERATOR = 2
    ADMIN = 3


# Backwards-compatible single-token mode: API_TOKEN alone grants operator
# (the previous behavior — it gated /command, /ai-command, /ai-reset).
# For richer setups, configure any subset of:
#   API_TOKEN_VIEWER   → read journals, no mutation
#   API_TOKEN_OPERATOR → all commands, no token management
#   API_TOKEN_ADMIN    → everything, including future admin-only ops
# Each var also supports the *_FILE variant via env_or_file().

_TOKEN_ENV_TO_ROLE = {
    "API_TOKEN_ADMIN": Role.ADMIN,
    "API_TOKEN_OPERATOR": Role.OPERATOR,
    "API_TOKEN_VIEWER": Role.VIEWER,
    "API_TOKEN": Role.OPERATOR,  # legacy
}


def _current_tokens() -> dict[str, Role]:
    """Snapshot of (token → role). Resolved fresh on every call so test
    fixtures and live config changes take effect without import-time caching."""
    out: dict[str, Role] = {}
    for env_name, role in _TOKEN_ENV_TO_ROLE.items():
        value = env_or_file(env_name)
        if not value:
            continue
        # Comma-separated to allow rotation: API_TOKEN_OPERATOR="oldT,newT".
        for token in value.split(","):
            token = token.strip()
            if not token:
                continue
            # If the same token is listed under multiple roles, keep the
            # highest — explicit promotion wins over implicit lower grant.
            if out.get(token, Role.NONE) < role:
                out[token] = role
    return out


def auth_enabled() -> bool:
    return bool(_current_tokens())


def _resolve_bearer(header: str) -> tuple[str, Role] | None:
    if not header.lower().startswith("bearer "):
        return None
    presented = header.split(" ", 1)[1].strip()
    if not presented:
        return None
    for token, role in _current_tokens().items():
        if secrets.compare_digest(presented, token):
            return presented, role
    return None


def require_role(min_role: Role):
    """Build a FastAPI dependency that enforces the given minimum role.

    Returns the resolved Role so handlers can inspect the caller's privilege
    level (e.g. to redact data for VIEWER vs ADMIN)."""

    async def _dep(request: Request) -> Role:
        if not auth_enabled():
            # Demo / single-user dev mode — auth off, treat everyone as admin.
            return Role.ADMIN
        match = _resolve_bearer(request.headers.get("authorization", ""))
        if match is None:
            if not request.headers.get("authorization"):
                raise HTTPException(status_code=401, detail="missing bearer token")
            raise HTTPException(status_code=403, detail="invalid token")
        _, role = match
        if role < min_role:
            raise HTTPException(
                status_code=403,
                detail=f"requires role {min_role.name}, token has {role.name}",
            )
        return role

    return _dep


# Convenience pre-built dependencies for routes that just need the gate.
require_viewer = require_role(Role.VIEWER)
require_operator = require_role(Role.OPERATOR)
require_admin = require_role(Role.ADMIN)


# Legacy entry point kept for callers that don't need a specific role.
require_token = require_role(Role.OPERATOR)


async def require_token_ws(ws: WebSocket, min_role: Role = Role.OPERATOR) -> Role | None:
    """WebSocket auth: token comes via ?token=... (browsers can't set
    Authorization on WS upgrades). Closes with 4401 on missing/invalid,
    4403 on insufficient role. Returns the resolved Role on success,
    None on failure."""
    if not auth_enabled():
        return Role.ADMIN
    presented = ws.query_params.get("token", "")
    if not presented:
        await ws.close(code=4401, reason="invalid or missing token")
        return None
    for token, role in _current_tokens().items():
        if secrets.compare_digest(presented, token):
            if role < min_role:
                await ws.close(
                    code=4403,
                    reason=f"requires {min_role.name}, has {role.name}",
                )
                return None
            return role
    await ws.close(code=4401, reason="invalid or missing token")
    return None
