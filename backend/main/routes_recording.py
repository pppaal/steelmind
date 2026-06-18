"""Session recording: capture the broadcast event timeline and export it."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_operator, require_viewer
from .context import ctx
from .schemas import ReplayRequest

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
    return {**ctx.recorder.status(), "replaying": ctx.replaying}


@router.post("/recording/replay", dependencies=[Depends(require_operator)])
async def recording_replay(req: ReplayRequest) -> dict:
    """Re-broadcast a timeline over /ws (the current recording when `events`
    is omitted), preserving timing scaled by `speed` (clamped to 0.1–10x)."""
    events = req.events if req.events is not None else ctx.recorder.export()["events"]
    if not events:
        raise HTTPException(status_code=400, detail="nothing to replay")
    speed = min(10.0, max(0.1, req.speed))
    ctx.start_replay(events, speed)
    return {"ok": True, "count": len(events), "speed": speed, "replaying": True}


@router.post("/recording/replay/stop", dependencies=[Depends(require_operator)])
async def recording_replay_stop() -> dict:
    ctx.stop_replay()
    return {"ok": True, "replaying": False}


@router.get("/recording/export", dependencies=[Depends(require_viewer)])
async def recording_export() -> dict:
    """The full timeline — `events: [{t, event}]` — for offline analysis."""
    return ctx.recorder.export()
