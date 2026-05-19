from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import random
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .ai_commander import AICommander, AICommanderError
from .behavior_tree import BehaviorTree
from .behaviors import BEHAVIOR_DESCRIPTIONS, BEHAVIORS
from .journal import Journal
from .models import (
    CommandRequest,
    CommandResponse,
    RobotState,
    SensorData,
    SensorEvent,
    StatusEvent,
    Vector3,
)
from .plan_validator import validate_plan
from .rate_limit import TokenBucket
from .state_machine import InvalidTransitionError, StateMachine

load_dotenv(Path(__file__).parent / ".env")

logger = logging.getLogger("steelmind")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")

SENSOR_HZ = float(os.getenv("SENSOR_HZ", "20"))
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
AI_RATE_PER_SEC = float(os.getenv("AI_RATE_PER_SEC", "0.5"))  # 1 call / 2s sustained
AI_RATE_BURST = float(os.getenv("AI_RATE_BURST", "3"))
JOURNAL_DB = os.getenv("JOURNAL_DB", "steelmind.db")


class ConnectionManager:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, payload: BaseModel | dict) -> None:
        if isinstance(payload, BaseModel):
            message = payload.model_dump_json()
        else:
            message = json.dumps(payload, default=str)
        async with self._lock:
            targets = list(self._clients)
        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception:
                await self.disconnect(ws)

    @property
    def count(self) -> int:
        return len(self._clients)


def simulate_sensor(t: float, state: RobotState, behavior: str | None) -> SensorData:
    hip_left = 0.0
    hip_right = 0.0
    knee_left = 0.0
    knee_right = 0.0
    shoulder_left = 0.0
    shoulder_right = 0.0
    body_tilt_x = 0.0
    body_tilt_y = 0.0

    if state == RobotState.WALKING:
        hip_left = 0.4 * math.sin(t * 3)
        hip_right = -0.4 * math.sin(t * 3)
        knee_left = 0.3 * max(0.0, math.cos(t * 3))
        knee_right = 0.3 * max(0.0, -math.cos(t * 3))
        shoulder_left = -0.3 * math.sin(t * 3)
        shoulder_right = 0.3 * math.sin(t * 3)
        body_tilt_x = 0.08 * math.sin(t * 3)
    elif state == RobotState.EXECUTING and behavior == "wave":
        shoulder_right = -1.6 + 0.4 * math.sin(t * 6)
        shoulder_left = 0.05 * math.sin(t * 6)
    elif state == RobotState.EXECUTING and behavior == "squat":
        depth = 0.5 * (1 - math.cos(t * 2)) / 2
        hip_left = depth
        hip_right = depth
        knee_left = -depth * 1.6
        knee_right = -depth * 1.6
    elif state == RobotState.EXECUTING and behavior == "patrol":
        hip_left = 0.45 * math.sin(t * 4)
        hip_right = -0.45 * math.sin(t * 4)
        knee_left = 0.35 * max(0.0, math.cos(t * 4))
        knee_right = 0.35 * max(0.0, -math.cos(t * 4))
        body_tilt_y = 0.4 * math.sin(t * 0.6)
    elif state == RobotState.EXECUTING and behavior == "dance":
        hip_left = 0.25 * math.sin(t * 5)
        hip_right = -0.25 * math.sin(t * 5)
        shoulder_left = -0.9 + 0.6 * math.sin(t * 5)
        shoulder_right = -0.9 - 0.6 * math.sin(t * 5)
        body_tilt_x = 0.15 * math.sin(t * 2.5)
    elif state == RobotState.EXECUTING:
        shoulder_left = 0.15 * math.sin(t * 3)
        shoulder_right = -0.15 * math.sin(t * 3)
    elif state == RobotState.STANDING:
        body_tilt_x = 0.01 * math.sin(t * 1.2)
    else:  # IDLE
        body_tilt_x = 0.005 * math.sin(t * 0.8)

    return SensorData(
        imu_orientation=Vector3(x=body_tilt_x, y=body_tilt_y, z=0.0),
        imu_angular_velocity=Vector3(
            x=body_tilt_x * math.cos(t),
            y=body_tilt_y * math.cos(t),
            z=0.0,
        ),
        imu_linear_acceleration=Vector3(z=9.81 + random.uniform(-0.05, 0.05)),
        joint_positions={
            "hip_left": hip_left,
            "hip_right": hip_right,
            "knee_left": knee_left,
            "knee_right": knee_right,
            "shoulder_left": shoulder_left,
            "shoulder_right": shoulder_right,
        },
        joint_velocities={
            "hip_left": hip_left,
            "hip_right": hip_right,
        },
        battery_voltage=24.0 + random.uniform(-0.1, 0.1),
        battery_percent=max(0.0, 100.0 - (t * 0.01) % 100.0),
    )


class Metrics:
    """Tiny counter set rendered as Prometheus text on /metrics."""

    def __init__(self) -> None:
        self.transitions_total = 0
        self.ai_commands_total = 0
        self.ai_repairs_total = 0
        self.ai_errors_total = 0
        self.rate_limited_total = 0
        self.sensor_frames_total = 0

    def render(self, *, ws_clients: int, ai_history: int) -> str:
        lines = [
            "# HELP steelmind_transitions_total Total state transitions broadcast.",
            "# TYPE steelmind_transitions_total counter",
            f"steelmind_transitions_total {self.transitions_total}",
            "# HELP steelmind_ai_commands_total AI commander requests successfully translated.",
            "# TYPE steelmind_ai_commands_total counter",
            f"steelmind_ai_commands_total {self.ai_commands_total}",
            "# HELP steelmind_ai_repairs_total AI plans repaired after validator rejection.",
            "# TYPE steelmind_ai_repairs_total counter",
            f"steelmind_ai_repairs_total {self.ai_repairs_total}",
            "# HELP steelmind_ai_errors_total AI commander upstream/translation errors.",
            "# TYPE steelmind_ai_errors_total counter",
            f"steelmind_ai_errors_total {self.ai_errors_total}",
            "# HELP steelmind_rate_limited_total AI requests rejected by the rate limiter.",
            "# TYPE steelmind_rate_limited_total counter",
            f"steelmind_rate_limited_total {self.rate_limited_total}",
            "# HELP steelmind_sensor_frames_total Sensor frames broadcast over /ws.",
            "# TYPE steelmind_sensor_frames_total counter",
            f"steelmind_sensor_frames_total {self.sensor_frames_total}",
            "# HELP steelmind_ws_clients Current connected WebSocket clients.",
            "# TYPE steelmind_ws_clients gauge",
            f"steelmind_ws_clients {ws_clients}",
            "# HELP steelmind_ai_history AI conversation memory turns.",
            "# TYPE steelmind_ai_history gauge",
            f"steelmind_ai_history {ai_history}",
            "",
        ]
        return "\n".join(lines)


class AppContext:
    def __init__(self) -> None:
        self.state_machine = StateMachine()
        self.manager = ConnectionManager()
        self.ai = AICommander(api_key=ANTHROPIC_API_KEY)
        self.ai_rate = TokenBucket(rate_per_sec=AI_RATE_PER_SEC, burst=AI_RATE_BURST)
        self.journal = Journal(JOURNAL_DB)
        self.metrics = Metrics()
        self.background_tasks: set[asyncio.Task[None]] = set()
        self.current_tree: BehaviorTree | None = None
        self._sensor_task: asyncio.Task[None] | None = None
        self._transition_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self.journal.init()
        self._sensor_task = asyncio.create_task(self._sensor_loop())
        self._transition_task = asyncio.create_task(self._transition_loop())

    async def stop(self) -> None:
        for task in (self._sensor_task, self._transition_task):
            if task:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        if self.current_tree:
            await self.current_tree.stop()

    async def _sensor_loop(self) -> None:
        period = 1.0 / SENSOR_HZ
        t = 0.0
        while True:
            status = self.state_machine.status
            data = simulate_sensor(t, status.state, status.current_behavior)
            await self.manager.broadcast(SensorEvent(data=data))
            self.metrics.sensor_frames_total += 1
            t += period
            await asyncio.sleep(period)

    async def _transition_loop(self) -> None:
        queue = self.state_machine.subscribe()
        try:
            while True:
                event = await queue.get()
                await self.manager.broadcast(event)
                await self.manager.broadcast(StatusEvent(status=self.state_machine.status))
                self.metrics.transitions_total += 1
                try:
                    await self.journal.record_transition(
                        event.from_state.value, event.to_state.value, event.reason
                    )
                except Exception:
                    logger.exception("journal record_transition failed")
        finally:
            self.state_machine.unsubscribe(queue)


ctx = AppContext()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await ctx.start()
    logger.info("steelmind backend started (anthropic_key=%s)", bool(ANTHROPIC_API_KEY))
    try:
        yield
    finally:
        await ctx.stop()


app = FastAPI(title="steelmind backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "state": ctx.state_machine.state.value,
        "clients": ctx.manager.count,
        "ai_enabled": ctx.ai.enabled,
        "ai_history": ctx.ai.history_length,
        "time": datetime.now(UTC).isoformat(),
    }


@app.post("/ai-reset")
async def ai_reset() -> dict:
    ctx.ai.reset_history()
    return {"ok": True, "ai_history": ctx.ai.history_length}


@app.get("/metrics")
async def metrics() -> Response:
    body = ctx.metrics.render(
        ws_clients=ctx.manager.count,
        ai_history=ctx.ai.history_length,
    )
    return Response(content=body, media_type="text/plain; version=0.0.4")


@app.get("/journal/transitions")
async def journal_transitions(limit: int = 100) -> dict:
    return {"transitions": await ctx.journal.list_transitions(limit=min(limit, 1000))}


@app.get("/journal/ai-commands")
async def journal_ai_commands(limit: int = 100) -> dict:
    return {"ai_commands": await ctx.journal.list_ai_commands(limit=min(limit, 1000))}


@app.get("/journal/counts")
async def journal_counts() -> dict:
    return await ctx.journal.counts()


@app.get("/status")
async def status() -> dict:
    return ctx.state_machine.status.model_dump()


@app.post("/command", response_model=CommandResponse)
async def command(req: CommandRequest) -> CommandResponse:
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


async def _run_behavior(name: str) -> None:
    if ctx.current_tree and ctx.current_tree.is_running:
        await ctx.current_tree.stop()
        # Cancelled BT may have set behavior name but skipped the exit action.
        if ctx.state_machine.status.current_behavior is not None:
            ctx.state_machine.set_behavior(None)
        if ctx.state_machine.state == RobotState.EXECUTING:
            await ctx.state_machine.transition(
                RobotState.STANDING, reason="behavior:cancelled", force=True
            )
    tree = BEHAVIORS[name](ctx.state_machine)
    ctx.current_tree = tree
    tree.start()


@app.get("/behaviors")
async def list_behaviors() -> dict:
    return {
        "behaviors": [
            {"name": name, "description": BEHAVIOR_DESCRIPTIONS.get(name, "")}
            for name in BEHAVIORS
        ]
    }


class AICommandRequest(BaseModel):
    text: str


class AIPlanStepResult(BaseModel):
    command: str
    params: dict = {}
    executed: bool
    detail: str | None = None


class AICommandResponse(BaseModel):
    explanation: str
    steps: list[AIPlanStepResult]
    fully_executed: bool


@app.post("/ai-command", response_model=AICommandResponse)
async def ai_command(req: AICommandRequest, request: Request) -> AICommandResponse:
    if not ctx.ai.enabled:
        raise HTTPException(status_code=503, detail="AI commander disabled (no ANTHROPIC_API_KEY)")

    client_key = request.client.host if request.client else "unknown"
    allowed, retry_after = await ctx.ai_rate.allow(client_key)
    if not allowed:
        ctx.metrics.rate_limited_total += 1
        raise HTTPException(
            status_code=429,
            detail=f"rate limited; retry in {retry_after:.1f}s",
            headers={"Retry-After": f"{retry_after:.1f}"},
        )

    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    repaired = False
    try:
        plan = await ctx.ai.translate(text, ctx.state_machine.status)
        ok, error = validate_plan(plan.steps, ctx.state_machine.state)
        if not ok and error:
            logger.info("plan invalid, repairing: %s", error)
            plan = await ctx.ai.translate(
                text, ctx.state_machine.status, repair_context=error
            )
            repaired = True
            ctx.metrics.ai_repairs_total += 1
    except AICommanderError as e:
        ctx.metrics.ai_errors_total += 1
        raise HTTPException(status_code=502, detail=str(e)) from e

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
    )


async def _execute_plan(steps: list) -> None:
    for step in steps:
        try:
            await command(CommandRequest(command=step.command, params=step.params))
        except HTTPException as e:
            await ctx.manager.broadcast(
                {"type": "plan_step_failed", "command": step.command, "detail": str(e.detail)}
            )
            return
        # If we just kicked off a behavior, wait until it finishes before
        # advancing to the next step. The behavior tree itself transitions
        # the state machine back to STANDING when done.
        if step.command == "execute" and ctx.current_tree is not None:
            await ctx.current_tree.wait()
        else:
            await asyncio.sleep(0.4)
    await ctx.manager.broadcast({"type": "plan_completed", "step_count": len(steps)})


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ctx.manager.connect(ws)
    try:
        await ws.send_text(StatusEvent(status=ctx.state_machine.status).model_dump_json())
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_text(json.dumps({"type": "error", "detail": "invalid json"}))
                continue
            await _handle_ws_message(ws, msg)
    except WebSocketDisconnect:
        pass
    finally:
        await ctx.manager.disconnect(ws)


async def _handle_ws_message(ws: WebSocket, msg: dict) -> None:
    kind = msg.get("type")
    if kind == "ping":
        await ws.send_text(json.dumps({"type": "pong"}))
    elif kind == "command":
        try:
            req = CommandRequest(**msg.get("payload", {}))
            resp = await command(req)
            await ws.send_text(resp.model_dump_json())
        except HTTPException as e:
            await ws.send_text(json.dumps({"type": "error", "detail": e.detail}))
    else:
        await ws.send_text(json.dumps({"type": "error", "detail": f"unknown message: {kind}"}))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
