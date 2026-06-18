"""Session recording: capture the broadcast event timeline and export it."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import require_operator, require_viewer
from .context import ctx

router = APIRouter()


@router.post("/recording/start", dependencies=[Depends(require_operator)])
async def recording_start() -> dict:
    """Begin a new recording (discards any previous one)."""
    ctx.recorder.start()
    return ctx.recorder.status()


@router.post("/recording/stop", dependencies=[Depends(require_operator)])
async def recording_stop() -> dict:
    ctx.recorder.stop()
    return ctx.recorder.status()


@router.get("/recording", dependencies=[Depends(require_viewer)])
async def recording_status() -> dict:
    return ctx.recorder.status()


@router.get("/recording/export", dependencies=[Depends(require_viewer)])
async def recording_export() -> dict:
    """The full timeline — `events: [{t, event}]` — for offline analysis."""
    return ctx.recorder.export()
