"""Motion and command execution: the shared, route-free logic that turns
commands / behaviors / keyframes / reach targets / routines / AI plans into
trajectories played through the HAL. Imported by the route modules.
"""

from __future__ import annotations

import asyncio
import time

from fastapi import HTTPException

from ..ai_commander import PlanStep
from ..behaviors import BEHAVIORS
from ..models import CommandRequest, CommandResponse, RobotState
from ..state_machine import InvalidTransitionError
from ..trajectory import Trajectory, min_jerk
from .config import KEYFRAME_SEGMENT_SEC, SENSOR_HZ, logger
from .context import ctx
from .schemas import (
    BehaviorStep,
    CommandStep,
    KeyframesStep,
    ReachStep,
    RoutineBody,
    RoutineStep,
    WaitStep,
)


async def _dispatch_command(req: CommandRequest) -> CommandResponse:
    """Pure command dispatcher — no FastAPI dependencies, no auth. Called by
    both the HTTP route handler and the in-process plan executor / WS handler.
    Raises HTTPException for invalid transitions / unknown commands so HTTP
    callers can let FastAPI render the error and in-process callers can catch
    a single exception type."""
    cmd = req.command.lower()
    try:
        if cmd == "stand":
            await ctx.state_machine.transition(RobotState.STANDING, reason="command:stand")
        elif cmd == "sit" or cmd == "idle":
            await ctx.state_machine.transition(RobotState.IDLE, reason="command:idle")
        elif cmd == "walk":
            await ctx.state_machine.transition(RobotState.WALKING, reason="command:walk")
        elif cmd == "stop":
            await ctx.state_machine.transition(RobotState.STANDING, reason="command:stop")
        elif cmd == "execute":
            behavior = req.params.get("behavior", "demo")
            if behavior not in BEHAVIORS:
                raise HTTPException(status_code=400, detail=f"unknown behavior: {behavior}")
            await _run_behavior(behavior)
        else:
            raise HTTPException(status_code=400, detail=f"unknown command: {req.command}")
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return CommandResponse(ok=True, message=f"{cmd} accepted", status=ctx.state_machine.status)


async def _play_trajectory(label: str, traj: Trajectory) -> None:
    """Background task: sample `traj` at SENSOR_HZ and push each waypoint
    through the HAL. Returns the state machine to STANDING on completion.
    Cancellable — _play() cancels the in-flight task when a new motion
    preempts. `label` is the behavior/keyframe name reported as
    current_behavior."""
    assert ctx.hardware is not None
    period = 1.0 / SENSOR_HZ
    started = time.monotonic()
    try:
        await ctx.state_machine.transition(
            RobotState.EXECUTING, reason=f"play:{label}", force=True
        )
        await ctx.state_machine.set_behavior(label)
        while True:
            t = time.monotonic() - started
            await ctx.hardware.write(traj.sample(t))
            if t >= traj.duration:
                break
            await asyncio.sleep(period)
    except asyncio.CancelledError:
        raise
    finally:
        await ctx.state_machine.set_behavior(None)
        if ctx.state_machine.state == RobotState.EXECUTING:
            try:
                await ctx.state_machine.transition(
                    RobotState.STANDING, reason=f"play:{label}:done", force=True
                )
            except Exception:
                logger.exception("post-play transition failed")


async def _play(label: str, traj: Trajectory) -> None:
    """Preempt any running motion and start a new trajectory in the
    background. Awaits the EXECUTING transition before returning so HTTP
    responses carry the real new state."""
    async with ctx.behavior_lock:
        prev = ctx.current_behavior_task
        if prev and not prev.done():
            prev.cancel()
            try:
                await prev
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("previous play task raised on cancel")
        if ctx.hardware:
            await ctx.hardware.enable()
        ctx.current_behavior_task = asyncio.create_task(_play_trajectory(label, traj))
        for _ in range(50):
            if (
                ctx.state_machine.state == RobotState.EXECUTING
                and ctx.state_machine.status.current_behavior == label
            ):
                break
            await asyncio.sleep(0.01)


async def _run_behavior(name: str) -> None:
    await _play(name, BEHAVIORS[name].build())


def _validate_routine_steps(steps: list[RoutineStep]) -> None:
    """Reject steps that reference things that don't exist, so a routine
    can't be saved that's guaranteed to fail at run time."""
    for i, step in enumerate(steps):
        if isinstance(step, BehaviorStep) and step.behavior not in BEHAVIORS:
            raise HTTPException(status_code=400, detail=f"step {i}: unknown behavior {step.behavior}")
        if isinstance(step, ReachStep) and ctx.chain is None:
            raise HTTPException(status_code=400, detail=f"step {i}: reach needs a kinematic chain")
        if isinstance(step, WaitStep) and step.seconds < 0:
            raise HTTPException(status_code=400, detail=f"step {i}: wait seconds must be >= 0")


async def _await_motion() -> None:
    """Block until the current background motion (behavior/keyframe/reach)
    finishes, so routine steps run strictly one after another."""
    task = ctx.current_behavior_task
    if task and not task.done():
        try:
            await task
        except asyncio.CancelledError:
            pass


async def _run_routine(name: str, steps: list[RoutineStep]) -> None:
    """Execute a routine step-by-step in the background, awaiting each
    motion's completion. Broadcasts progress so the UI can follow along."""
    await ctx.manager.broadcast({"type": "routine_started", "name": name, "steps": len(steps)})
    try:
        for i, step in enumerate(steps):
            await ctx.manager.broadcast(
                {"type": "routine_step", "name": name, "index": i, "step": step.type}
            )
            if isinstance(step, WaitStep):
                await asyncio.sleep(step.seconds)
            elif isinstance(step, CommandStep):
                await _dispatch_command(CommandRequest(command=step.command, params=step.params))
                await _await_motion()
            elif isinstance(step, BehaviorStep):
                await _play(step.behavior, BEHAVIORS[step.behavior].build())
                await _await_motion()
            elif isinstance(step, KeyframesStep):
                assert ctx.hardware is not None
                snap = await ctx.hardware.read()
                start = {n: js.position for n, js in snap.joints.items()}
                traj = ctx.keyframes.build_trajectory(
                    step.names, segment_duration=KEYFRAME_SEGMENT_SEC, start_pose=start
                )
                await _play(f"keyframes:{'+'.join(step.names)}", traj)
                await _await_motion()
            elif isinstance(step, ReachStep):
                assert ctx.hardware is not None and ctx.chain is not None
                snap = await ctx.hardware.read()
                seed = {n: js.position for n, js in snap.joints.items()}
                limits = {j.name: (j.lower_limit, j.upper_limit) for j in ctx.joints}
                angles, _, _ = ctx.chain.inverse((step.x, step.y), seed=seed, limits=limits)
                traj = min_jerk(seed, {**seed, **angles}, duration=KEYFRAME_SEGMENT_SEC)
                await _play(f"reach:({step.x:.2f},{step.y:.2f})", traj)
                await _await_motion()
        await ctx.manager.broadcast({"type": "routine_complete", "name": name})
    except asyncio.CancelledError:
        await ctx.manager.broadcast({"type": "routine_cancelled", "name": name})
        raise
    except Exception as e:
        logger.exception("routine %s failed", name)
        await ctx.manager.broadcast({"type": "routine_failed", "name": name, "detail": str(e)})


def _coerce_routine(raw_steps: list[dict]) -> tuple[RoutineBody | None, str | None]:
    """Validate loosely-typed AI steps against the strict routine models,
    then run the same semantic checks save_routine uses. Returns
    (body, None) on success or (None, error) so the caller can ask the AI
    to repair."""
    try:
        body = RoutineBody(steps=raw_steps)  # type: ignore[arg-type]
    except Exception as e:
        return None, f"schema error: {e}"
    try:
        _validate_routine_steps(body.steps)
    except HTTPException as e:
        return None, str(e.detail)
    return body, None


async def _execute_plan(steps: list[PlanStep]) -> None:
    for step in steps:
        try:
            await _dispatch_command(CommandRequest(command=step.command, params=step.params))
        except HTTPException as e:
            await ctx.manager.broadcast(
                {"type": "plan_step_failed", "command": step.command, "detail": str(e.detail)}
            )
            return
        # If we just kicked off a behavior, wait until its trajectory task
        # finishes before advancing — otherwise the next step would preempt
        # the motion mid-flight. _play() runs the behavior as
        # current_behavior_task, which _await_motion() joins on.
        if step.command == "execute":
            await _await_motion()
        else:
            await asyncio.sleep(0.4)
    await ctx.manager.broadcast({"type": "plan_completed", "step_count": len(steps)})
