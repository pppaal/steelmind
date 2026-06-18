"""AI commander endpoints: natural-language → plan / routine, and reset."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from ..ai_commander import AICommanderError
from ..auth import require_admin, require_operator
from ..plan_validator import validate_plan
from .config import logger
from .context import _client_ip, _session_key, _validate_name, ctx, require_deadman
from .motion import _coerce_routine, _execute_plan, _run_routine
from .schemas import (
    AICommandRequest,
    AICommandResponse,
    AIPlanStepResult,
    AIRoutineRequest,
)

router = APIRouter()


@router.post("/ai-reset", dependencies=[Depends(require_admin)])
async def ai_reset(request: Request) -> dict:
    sid = request.headers.get("x-session-id")
    ctx.ai.reset_history(sid[:64] if sid else None)
    return {"ok": True, "ai_history": ctx.ai.history_length()}


@router.post("/ai-routine", dependencies=[Depends(require_operator)])
async def ai_routine(req: AIRoutineRequest, request: Request) -> dict:
    """Natural language → a saved routine. The AI composes loosely-typed
    steps; we validate them strictly with the routine step models (one
    repair retry on failure), save under `name`, and optionally run."""
    if not ctx.ai.enabled:
        raise HTTPException(status_code=503, detail="AI commander disabled (no ANTHROPIC_API_KEY)")
    if req.run:
        require_deadman()
    _validate_name(req.name, "routine")
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    allowed, retry_after = await ctx.ai_rate.allow(_client_ip(request))
    if not allowed:
        ctx.metrics.rate_limited_total += 1
        raise HTTPException(status_code=429, detail=f"rate limited; retry in {retry_after:.1f}s")

    has_chain = ctx.chain is not None
    started = time.monotonic()
    try:
        result = await ctx.ai.compose_routine(text, has_chain=has_chain)
        body, error = _coerce_routine(result.steps)
        if body is None:
            result = await ctx.ai.compose_routine(text, has_chain=has_chain, repair_context=error)
            body, error = _coerce_routine(result.steps)
            if body is None:
                ctx.metrics.ai_errors_total += 1
                raise HTTPException(status_code=502, detail=f"AI produced an invalid routine: {error}")
    except AICommanderError as e:
        ctx.metrics.ai_errors_total += 1
        raise HTTPException(status_code=502, detail=str(e)) from e
    finally:
        ctx.metrics.observe_ai_latency_ms((time.monotonic() - started) * 1000.0)

    ctx.metrics.ai_commands_total += 1
    await ctx.routines.save(req.name, [s.model_dump() for s in body.steps])

    ran = False
    if req.run:
        if ctx.routine_task and not ctx.routine_task.done():
            ctx.routine_task.cancel()
        task = asyncio.create_task(_run_routine(req.name, body.steps))
        ctx.routine_task = task
        ctx.background_tasks.add(task)
        task.add_done_callback(ctx.background_tasks.discard)
        ran = True

    return {
        "ok": True,
        "name": req.name,
        "explanation": result.explanation,
        "steps": [s.model_dump() for s in body.steps],
        "running": ran,
    }


@router.post(
    "/ai-command",
    response_model=AICommandResponse,
    dependencies=[Depends(require_operator)],
)
async def ai_command(req: AICommandRequest, request: Request) -> AICommandResponse:
    text_preview = (req.text or "").strip()
    if not text_preview:
        raise HTTPException(status_code=400, detail="text is required")
    if len(text_preview) > 500:
        raise HTTPException(status_code=413, detail="text too long (max 500 chars)")

    if not ctx.ai.enabled:
        raise HTTPException(status_code=503, detail="AI commander disabled (no ANTHROPIC_API_KEY)")
    require_deadman()

    client_key = _client_ip(request)
    allowed, retry_after = await ctx.ai_rate.allow(client_key)
    if not allowed:
        ctx.metrics.rate_limited_total += 1
        raise HTTPException(
            status_code=429,
            detail=f"rate limited; retry in {retry_after:.1f}s",
            headers={"Retry-After": f"{retry_after:.1f}"},
        )

    text = text_preview

    session = _session_key(request)
    repaired = False
    started = time.monotonic()
    try:
        plan = await ctx.ai.translate(text, ctx.state_machine.status, session=session)
        ok, error = validate_plan(plan.steps, ctx.state_machine.state)
        if not ok and error:
            logger.info("plan invalid, repairing: %s", error)
            plan = await ctx.ai.translate(
                text, ctx.state_machine.status, repair_context=error, session=session
            )
            repaired = True
            ctx.metrics.ai_repairs_total += 1
            # Validate the repaired plan too; if still invalid, give up with
            # an explicit 502 the UI can surface to the user.
            ok2, error2 = validate_plan(plan.steps, ctx.state_machine.state)
            if not ok2:
                ctx.metrics.ai_errors_total += 1
                raise HTTPException(
                    status_code=502,
                    detail=f"AI could not produce a valid plan: {error2}",
                )
    except AICommanderError as e:
        ctx.metrics.ai_errors_total += 1
        raise HTTPException(status_code=502, detail=str(e)) from e
    finally:
        ctx.metrics.observe_ai_latency_ms((time.monotonic() - started) * 1000.0)

    ctx.metrics.ai_commands_total += 1
    try:
        await ctx.journal.record_ai_command(
            text=text,
            plan={"steps": [s.model_dump() for s in plan.steps], "explanation": plan.explanation},
            explanation=plan.explanation,
            repaired=repaired,
        )
    except Exception:
        logger.exception("journal record_ai_command failed")

    await ctx.manager.broadcast(
        {
            "type": "ai_command",
            "input": text,
            "command": plan.first.command,
            "params": plan.first.params,
            "explanation": plan.explanation,
            "step_count": len(plan.steps),
            "repaired": repaired,
        }
    )

    # Schedule the plan to run in the background so the HTTP call returns
    # immediately. Each step waits for behavior completion (when applicable)
    # before the next is dispatched. Hold a reference so the task isn't
    # garbage-collected mid-flight.
    task = asyncio.create_task(_execute_plan(plan.steps))
    ctx.background_tasks.add(task)
    task.add_done_callback(ctx.background_tasks.discard)

    # Optimistically return the plan; clients track real execution via /ws.
    return AICommandResponse(
        explanation=plan.explanation,
        steps=[
            AIPlanStepResult(command=s.command, params=s.params, executed=False, detail=None)
            for s in plan.steps
        ],
        fully_executed=False,
        repaired=repaired,
    )
