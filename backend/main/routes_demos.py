"""Demonstration capture endpoints for imitation learning: record labeled
episodes and export them in a LeRobotDataset-style schema."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_admin, require_operator, require_viewer
from .context import ctx
from .schemas import DemoStartRequest, DemoStopRequest

router = APIRouter()


@router.post("/demos/start", dependencies=[Depends(require_operator)])
async def demos_start(req: DemoStartRequest) -> dict:
    if ctx.demos.active:
        raise HTTPException(status_code=409, detail="an episode is already recording")
    ctx.demos.start(req.task)
    return ctx.demos.status()


@router.post("/demos/stop", dependencies=[Depends(require_operator)])
async def demos_stop(req: DemoStopRequest) -> dict:
    result = ctx.demos.stop(req.success, req.notes)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("detail", "no active episode"))
    return {**result, **ctx.demos.status()}


@router.get("/demos", dependencies=[Depends(require_viewer)])
async def demos_status() -> dict:
    return {**ctx.demos.status(), "episodes_meta": ctx.demos.episodes()}


@router.get("/demos/export", dependencies=[Depends(require_viewer)])
async def demos_export() -> dict:
    joint_names = sorted(j.name for j in ctx.joints)
    return ctx.demos.export(joint_names)


@router.delete("/demos", dependencies=[Depends(require_admin)])
async def demos_clear() -> dict:
    ctx.demos.clear()
    return ctx.demos.status()
