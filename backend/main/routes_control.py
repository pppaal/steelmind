"""Direct robot control: e-stop, jog, calibration, command dispatch."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_admin, require_operator, require_viewer
from ..behaviors import BEHAVIOR_DESCRIPTIONS, BEHAVIORS
from ..models import CommandRequest, CommandResponse, RobotState
from ..robot_config import load_config
from .config import MAX_JOG_RAD, ROBOT_CONFIG
from .context import _apply_calibration, ctx
from .motion import _dispatch_command
from .schemas import CalibrationRequest, JogRequest

router = APIRouter()


@router.post("/estop", dependencies=[Depends(require_operator)])
async def estop() -> dict:
    """Latching emergency stop. Cancels any active behavior/routine,
    force-transitions to IDLE, and cuts torque via the hardware. Subsequent
    writes are silently dropped until /estop/clear runs."""
    if ctx.routine_task and not ctx.routine_task.done():
        ctx.routine_task.cancel()
    if ctx.current_behavior_task and not ctx.current_behavior_task.done():
        ctx.current_behavior_task.cancel()
    if ctx.hardware:
        await ctx.hardware.estop()
    await ctx.state_machine.transition(RobotState.IDLE, reason="estop", force=True)
    await ctx.state_machine.set_behavior(None)
    await ctx.state_machine.set_error("estop latched")
    return {"ok": True, "estopped": True}


@router.post("/estop/clear", dependencies=[Depends(require_admin)])
async def estop_clear() -> dict:
    """Operator-initiated reset. Admin-only — clearing an E-stop should
    require human acknowledgement, not be reachable from a stuck script."""
    if ctx.hardware:
        await ctx.hardware.clear_estop()
    await ctx.state_machine.set_error(None)
    return {"ok": True, "estopped": False}


@router.post("/jog", dependencies=[Depends(require_operator)])
async def jog(req: JogRequest) -> dict:
    """Nudge a single joint by a small relative delta. The safe primitive
    for bring-up/testing — bounded by MAX_JOG_RAD and the joint's own soft
    limits (clamped inside the HAL). Reads current position, adds delta,
    writes the new absolute target."""
    if ctx.hardware is None:
        raise HTTPException(status_code=503, detail="hardware not ready")
    spec = next((j for j in ctx.joints if j.name == req.joint), None)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"unknown joint: {req.joint}")
    if abs(req.delta) > MAX_JOG_RAD:
        raise HTTPException(
            status_code=400,
            detail=f"delta {req.delta:.3f} exceeds MAX_JOG_RAD {MAX_JOG_RAD}",
        )
    await ctx.hardware.enable()
    snapshot = await ctx.hardware.read()
    current = snapshot.joints[req.joint].position if req.joint in snapshot.joints else 0.0
    target = spec.clamp(current + req.delta)
    await ctx.hardware.write({req.joint: target})
    return {"ok": True, "joint": req.joint, "target": target}


@router.get("/calibration", dependencies=[Depends(require_viewer)])
async def get_calibration() -> dict:
    return {"offsets": ctx.calibration.offsets}


@router.post("/calibration", dependencies=[Depends(require_admin)])
async def set_calibration(req: CalibrationRequest) -> dict:
    """Persist per-joint offsets and re-fold them into the live joint specs
    without a restart. Admin-only — miscalibration can drive a joint into a
    hard stop."""
    known = {j.name for j in ctx.joints}
    unknown = set(req.offsets) - known
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown joints: {sorted(unknown)}")
    await ctx.calibration.set_many(req.offsets)
    # Re-apply against the freshly-loaded config so offsets compose correctly
    # rather than stacking on the already-calibrated specs.
    ctx.joints = _apply_calibration(load_config(ROBOT_CONFIG), ctx.calibration)
    if ctx.hardware is not None:
        ctx.hardware.update_specs(ctx.joints)
    return {"ok": True, "offsets": ctx.calibration.offsets}


@router.post("/command", response_model=CommandResponse, dependencies=[Depends(require_operator)])
async def command(req: CommandRequest) -> CommandResponse:
    return await _dispatch_command(req)


@router.get("/behaviors")
async def list_behaviors() -> dict:
    return {
        "behaviors": [
            {"name": name, "description": BEHAVIOR_DESCRIPTIONS.get(name, "")}
            for name in BEHAVIORS
        ]
    }
