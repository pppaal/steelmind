"""Routine CRUD and execution endpoints."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_operator, require_viewer
from .context import _validate_name, ctx, require_deadman
from .motion import _run_routine, _validate_routine_steps
from .schemas import RoutineBody

router = APIRouter()


@router.get("/routines", dependencies=[Depends(require_viewer)])
async def list_routines() -> dict:
    return {"routines": ctx.routines.all()}


@router.get("/routines/{name}", dependencies=[Depends(require_viewer)])
async def get_routine(name: str) -> dict:
    """Single routine, for export/sharing. 404 if unknown."""
    steps = ctx.routines.get(name)
    if steps is None:
        raise HTTPException(status_code=404, detail=f"unknown routine: {name}")
    return {"name": name, "steps": steps}


@router.put("/routines/{name}", dependencies=[Depends(require_operator)])
async def save_routine(name: str, body: RoutineBody) -> dict:
    _validate_name(name, "routine")
    _validate_routine_steps(body.steps)
    await ctx.routines.save(name, [s.model_dump() for s in body.steps])
    return {"ok": True, "name": name, "steps": len(body.steps)}


@router.delete("/routines/{name}", dependencies=[Depends(require_operator)])
async def delete_routine(name: str) -> dict:
    if not await ctx.routines.delete(name):
        raise HTTPException(status_code=404, detail=f"unknown routine: {name}")
    return {"ok": True, "name": name}


@router.post("/routines/{name}/run", dependencies=[Depends(require_operator)])
async def run_routine(name: str) -> dict:
    require_deadman()
    raw = ctx.routines.get(name)
    if raw is None:
        raise HTTPException(status_code=404, detail=f"unknown routine: {name}")
    # Re-validate against the model (also coerces dict → typed steps).
    try:
        body = RoutineBody(steps=raw)  # type: ignore[arg-type]
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"corrupt routine: {e}") from e
    _validate_routine_steps(body.steps)
    # Cancel a routine already in flight before starting another.
    if ctx.routine_task and not ctx.routine_task.done():
        ctx.routine_task.cancel()
    task = asyncio.create_task(_run_routine(name, body.steps))
    ctx.routine_task = task
    ctx.background_tasks.add(task)
    task.add_done_callback(ctx.background_tasks.discard)
    return {"ok": True, "name": name, "steps": len(body.steps)}
