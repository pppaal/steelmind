from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import random
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .ai_commander import AICommander, AICommanderError
from .behavior_tree import Action, BehaviorTree, NodeStatus, Sequence
from .models import (
    CommandRequest,
    CommandResponse,
    RobotState,
    SensorData,
    SensorEvent,
    StateTransitionEvent,
    StatusEvent,
    Vector3,
)
from .state_machine import InvalidTransitionError, StateMachine

load_dotenv(Path(__file__).parent / ".env")

logger = logging.getLogger("steelmind")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")

SENSOR_HZ = float(os.getenv("SENSOR_HZ", "20"))
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")


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


def simulate_sensor(t: float, state: RobotState) -> SensorData:
    walking = state == RobotState.WALKING
    amp = 0.2 if walking else 0.02
    return SensorData(
        imu_orientation=Vector3(
            x=amp * math.sin(t),
            y=amp * math.cos(t * 0.8),
            z=0.0,
        ),
        imu_angular_velocity=Vector3(
            x=amp * math.cos(t),
            y=-amp * math.sin(t),
            z=0.0,
        ),
        imu_linear_acceleration=Vector3(z=9.81 + random.uniform(-0.05, 0.05)),
        joint_positions={
            "hip_left": amp * math.sin(t),
            "hip_right": -amp * math.sin(t),
            "knee_left": amp * math.cos(t),
            "knee_right": -amp * math.cos(t),
        },
        joint_velocities={
            "hip_left": amp * math.cos(t),
            "hip_right": -amp * math.cos(t),
        },
        battery_voltage=24.0 + random.uniform(-0.1, 0.1),
        battery_percent=max(0.0, 100.0 - (t * 0.01) % 100.0),
    )


class AppContext:
    def __init__(self) -> None:
        self.state_machine = StateMachine()
        self.manager = ConnectionManager()
        self.ai = AICommander(api_key=ANTHROPIC_API_KEY)
        self.current_tree: BehaviorTree | None = None
        self._sensor_task: asyncio.Task[None] | None = None
        self._transition_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
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
            data = simulate_sensor(t, self.state_machine.state)
            await self.manager.broadcast(SensorEvent(data=data))
            t += period
            await asyncio.sleep(period)

    async def _transition_loop(self) -> None:
        queue = self.state_machine.subscribe()
        try:
            while True:
                event = await queue.get()
                await self.manager.broadcast(event)
                await self.manager.broadcast(StatusEvent(status=self.state_machine.status))
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
        "time": datetime.now(timezone.utc).isoformat(),
    }


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
            await _run_demo_behavior(behavior)
        else:
            raise HTTPException(status_code=400, detail=f"unknown command: {req.command}")
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return CommandResponse(ok=True, message=f"{cmd} accepted", status=ctx.state_machine.status)


async def _run_demo_behavior(name: str) -> None:
    if ctx.current_tree and ctx.current_tree.is_running:
        await ctx.current_tree.stop()

    async def enter_executing() -> NodeStatus:
        await ctx.state_machine.transition(RobotState.EXECUTING, reason=f"behavior:{name}")
        ctx.state_machine.set_behavior(name)
        return NodeStatus.SUCCESS

    async def do_work() -> NodeStatus:
        await asyncio.sleep(1.0)
        return NodeStatus.SUCCESS

    async def exit_to_standing() -> NodeStatus:
        ctx.state_machine.set_behavior(None)
        await ctx.state_machine.transition(RobotState.STANDING, reason=f"behavior:{name}:done")
        return NodeStatus.SUCCESS

    tree = BehaviorTree(
        Sequence(
            name,
            [
                Action("enter", enter_executing),
                Action("work", do_work),
                Action("exit", exit_to_standing),
            ],
        )
    )
    ctx.current_tree = tree
    tree.start()


class AICommandRequest(BaseModel):
    text: str


class AICommandResponse(BaseModel):
    command: str
    params: dict = {}
    explanation: str
    executed: bool
    detail: str | None = None


@app.post("/ai-command", response_model=AICommandResponse)
async def ai_command(req: AICommandRequest) -> AICommandResponse:
    if not ctx.ai.enabled:
        raise HTTPException(status_code=503, detail="AI commander disabled (no ANTHROPIC_API_KEY)")

    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    try:
        result = await ctx.ai.translate(text, ctx.state_machine.status)
    except AICommanderError as e:
        raise HTTPException(status_code=502, detail=str(e))

    await ctx.manager.broadcast(
        {
            "type": "ai_command",
            "input": text,
            "command": result.command,
            "params": result.params,
            "explanation": result.explanation,
        }
    )

    try:
        await command(CommandRequest(command=result.command, params=result.params))
        executed = True
        detail = None
    except HTTPException as e:
        executed = False
        detail = str(e.detail)

    return AICommandResponse(
        command=result.command,
        params=result.params,
        explanation=result.explanation,
        executed=executed,
        detail=detail,
    )


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
