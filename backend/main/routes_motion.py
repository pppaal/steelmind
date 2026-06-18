"""Keyframe teach/replay and forward/inverse kinematics endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_operator, require_viewer
from ..preview import simulate_trajectory, trajectory_zone_violation
from ..trajectory import min_jerk
from .config import KEYFRAME_SEGMENT_SEC, SENSOR_HZ
from .context import _validate_name, ctx, require_deadman
from .motion import _play
from .schemas import KeyframePlayRequest, ReachRequest

router = APIRouter()


@router.get("/keyframes", dependencies=[Depends(require_viewer)])
async def list_keyframes() -> dict:
    return {"keyframes": ctx.keyframes.all()}


# NOTE: this literal route MUST be declared before /keyframes/{name} or the
# parameterized route shadows it (matching name="play").
@router.post("/keyframes/play", dependencies=[Depends(require_operator)])
async def play_keyframes(req: KeyframePlayRequest) -> dict:
    """Replay a sequence of taught poses as one smooth min-jerk motion."""
    if ctx.hardware is None:
        raise HTTPException(status_code=503, detail="hardware not ready")
    seg = req.segment_duration or KEYFRAME_SEGMENT_SEC
    snapshot = await ctx.hardware.read()
    start = {n: js.position for n, js in snapshot.joints.items()}
    try:
        traj = ctx.keyframes.build_trajectory(req.names, segment_duration=seg, start_pose=start)
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if req.dry_run:
        specs = {j.name: j for j in ctx.joints}
        return {
            "dry_run": True,
            "names": req.names,
            "preview": simulate_trajectory(traj, specs, hz=SENSOR_HZ, chain=ctx.chain, zone=ctx.safety_zone),
        }
    require_deadman()
    if ctx.chain is not None and ctx.safety_zone is not None:
        wall = trajectory_zone_violation(traj, ctx.chain, ctx.safety_zone, hz=SENSOR_HZ)
        if wall:
            raise HTTPException(status_code=422, detail=f"motion blocked by safety zone: {wall}")
    await _play(f"keyframes:{'+'.join(req.names)}", traj)
    return {"ok": True, "names": req.names, "duration": traj.duration}


@router.post("/keyframes/{name}", dependencies=[Depends(require_operator)])
async def record_keyframe(name: str) -> dict:
    """Capture the current joint positions under `name`. Pair with the
    bring-up tool's torque-off mode (or a future UI toggle) to teach poses
    by hand."""
    _validate_name(name, "keyframe")
    if ctx.hardware is None:
        raise HTTPException(status_code=503, detail="hardware not ready")
    snapshot = await ctx.hardware.read()
    pose = {n: js.position for n, js in snapshot.joints.items()}
    await ctx.keyframes.record(name, pose)
    return {"ok": True, "name": name, "pose": pose}


@router.delete("/keyframes/{name}", dependencies=[Depends(require_operator)])
async def delete_keyframe(name: str) -> dict:
    if not await ctx.keyframes.delete(name):
        raise HTTPException(status_code=404, detail=f"unknown keyframe: {name}")
    return {"ok": True, "name": name}


@router.get("/fk", dependencies=[Depends(require_viewer)])
async def forward_kinematics() -> dict:
    """End-effector (x, y) of the configured planar chain at the current
    joint angles. 400 if this robot config has no chain."""
    if ctx.chain is None:
        raise HTTPException(status_code=400, detail="no kinematic chain configured")
    if ctx.hardware is None:
        raise HTTPException(status_code=503, detail="hardware not ready")
    snapshot = await ctx.hardware.read()
    angles = {n: js.position for n, js in snapshot.joints.items()}
    x, y = ctx.chain.forward(angles)
    return {"x": x, "y": y, "reach": ctx.chain.reach}


@router.get("/workspace", dependencies=[Depends(require_viewer)])
async def workspace() -> dict:
    """Reachable-workspace envelope (annulus) for the planar chain, so a
    client can pre-validate reach targets without a round-trip per keystroke.
    400 if this robot config has no chain."""
    if ctx.chain is None:
        raise HTTPException(status_code=400, detail="no kinematic chain configured")
    limits = {j.name: (j.lower_limit, j.upper_limit) for j in ctx.joints}
    env = ctx.chain.workspace(limits)
    if ctx.safety_zone is not None:
        env["zone"] = ctx.safety_zone.as_dict()
    return env


@router.post("/reach", dependencies=[Depends(require_operator)])
async def reach(req: ReachRequest) -> dict:
    """Solve IK for a target (x, y) and move the chain there as a smooth
    min-jerk trajectory. Returns the solved angles and whether the target
    was reachable (if not, the arm goes to the closest reachable pose)."""
    if ctx.chain is None:
        raise HTTPException(status_code=400, detail="no kinematic chain configured")
    if ctx.hardware is None:
        raise HTTPException(status_code=503, detail="hardware not ready")

    snapshot = await ctx.hardware.read()
    seed = {n: js.position for n, js in snapshot.joints.items()}
    limits = {j.name: (j.lower_limit, j.upper_limit) for j in ctx.joints}
    angles, reached, residual = ctx.chain.inverse((req.x, req.y), seed=seed, limits=limits)

    # Build a min-jerk move from the current pose into the IK solution.
    seg = req.duration or KEYFRAME_SEGMENT_SEC
    traj = min_jerk(seed, {**seed, **angles}, duration=seg)
    if req.dry_run:
        specs = {j.name: j for j in ctx.joints}
        return {
            "dry_run": True,
            "reached": reached,
            "residual": residual,
            "angles": angles,
            "preview": simulate_trajectory(traj, specs, hz=SENSOR_HZ, chain=ctx.chain, zone=ctx.safety_zone),
        }
    require_deadman()
    if ctx.safety_zone is not None:
        wall = trajectory_zone_violation(traj, ctx.chain, ctx.safety_zone, hz=SENSOR_HZ)
        if wall:
            raise HTTPException(status_code=422, detail=f"motion blocked by safety zone: {wall}")
    await _play(f"reach:({req.x:.2f},{req.y:.2f})", traj)
    return {
        "ok": True,
        "reached": reached,
        "residual": residual,
        "angles": angles,
    }
