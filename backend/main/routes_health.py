"""Health/probe, metrics, status, and journal read endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response

from ..auth import auth_enabled, require_viewer
from .context import ctx

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    """Full-fat health/inventory endpoint. Used by /health-style consumers
    (the frontend) that want the operational details in one call.
    For k8s-style probes prefer /livez and /readyz."""
    return {
        "ok": True,
        "state": ctx.state_machine.state.value,
        "clients": ctx.manager.count,
        "ai_enabled": ctx.ai.enabled,
        "ai_history": ctx.ai.history_length(),
        "ai_sessions": ctx.ai.session_count,
        "auth_required": auth_enabled(),
        "ready": ctx.ready,
        "time": datetime.now(UTC).isoformat(),
    }


@router.get("/livez", include_in_schema=False)
async def livez() -> Response:
    """Liveness probe — cheap, returns 200 as long as the process loop is
    answering. A liveness probe failing means k8s restarts the pod."""
    return Response(content="ok", media_type="text/plain")


@router.get("/readyz", include_in_schema=False)
async def readyz() -> Response:
    """Readiness probe — 200 only when lifespan startup has completed and
    shutdown hasn't started. A failing readiness probe makes k8s stop
    routing traffic without restarting the pod, which is exactly what we
    want during a graceful shutdown."""
    if not ctx.ready:
        return Response(content="draining", media_type="text/plain", status_code=503)
    return Response(content="ready", media_type="text/plain")


@router.get("/metrics")
async def metrics() -> Response:
    body = ctx.metrics.render(
        ws_clients=ctx.manager.count,
        ai_history=ctx.ai.history_length(),
        ai_sessions=ctx.ai.session_count,
        state=ctx.state_machine.state.value,
        estopped=bool(ctx.state_machine.status.error),
        recording=ctx.recorder.active,
        replaying=ctx.replaying,
    )
    return Response(content=body, media_type="text/plain; version=0.0.4")


# Journal endpoints carry user-supplied text (AI prompts) and full transition
# history. /counts is just integers so it's safe to leave open for monitoring;
# the row-level endpoints require auth when API_TOKEN is set.
@router.get("/journal/transitions", dependencies=[Depends(require_viewer)])
async def journal_transitions(limit: int = 100) -> dict:
    return {"transitions": await ctx.journal.list_transitions(limit=min(limit, 1000))}


@router.get("/journal/ai-commands", dependencies=[Depends(require_viewer)])
async def journal_ai_commands(limit: int = 100) -> dict:
    return {"ai_commands": await ctx.journal.list_ai_commands(limit=min(limit, 1000))}


@router.get("/journal/counts")
async def journal_counts() -> dict:
    return await ctx.journal.counts()


@router.get("/status")
async def status() -> dict:
    return ctx.state_machine.status.model_dump()
