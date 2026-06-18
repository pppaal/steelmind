"""Simulation-only endpoints: inject faults (disturbance / jam) to exercise
the safety reflexes. Available only when ROBOT_HARDWARE exposes fault
injection (i.e. the physics sim)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_admin, require_viewer
from .context import ctx
from .schemas import SimFaultRequest

router = APIRouter()


def _fault_hw() -> Any:
    hw = ctx.hardware
    if hw is None or not hasattr(hw, "inject_fault"):
        raise HTTPException(
            status_code=400,
            detail="fault injection requires ROBOT_HARDWARE=sim",
        )
    return hw


@router.get("/sim", dependencies=[Depends(require_viewer)])
async def sim_status() -> dict:
    """Whether the running hardware backend supports fault injection, and any
    currently-active faults."""
    hw = ctx.hardware
    supported = hw is not None and hasattr(hw, "inject_fault")
    return {
        "sim": supported,
        "backend": type(hw).__name__ if hw else None,
        "faults": hw.faults() if supported else {},
    }


@router.post("/sim/fault", dependencies=[Depends(require_admin)])
async def sim_fault(req: SimFaultRequest) -> dict:
    """Inject a disturbance torque or a jam on a joint."""
    hw = _fault_hw()
    if req.joint not in {j.name for j in ctx.joints}:
        raise HTTPException(status_code=404, detail=f"unknown joint: {req.joint}")
    try:
        hw.inject_fault(req.joint, req.kind, req.value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "faults": hw.faults()}


@router.post("/sim/clear-faults", dependencies=[Depends(require_admin)])
async def sim_clear_faults() -> dict:
    hw = _fault_hw()
    hw.clear_faults()
    return {"ok": True, "faults": hw.faults()}
