from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .ai_commander import AICommander, AICommanderError, PlanStep
from .auth import (
    Role,
    auth_enabled,
    require_admin,
    require_operator,
    require_token_ws,
    require_viewer,
)
from .behavior_tree import BehaviorTree
from .behaviors import BEHAVIOR_DESCRIPTIONS, BEHAVIORS
from .hardware import RobotHardware, build_hardware
from .journal import Journal
from .journal_base import JournalBase
from .logging_setup import configure as configure_logging
from .middleware import RequestIdMiddleware, RequestSizeLimitMiddleware
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
from .robot_config import load_config
from .safety import Watchdog
from .secrets import env_or_file
from .state_machine import InvalidTransitionError, StateMachine
from .tracing import configure as configure_tracing

load_dotenv(Path(__file__).parent / ".env")

configure_logging()
logger = logging.getLogger("steelmind")

SENSOR_HZ = float(os.getenv("SENSOR_HZ", "20"))
ANTHROPIC_API_KEY = env_or_file("ANTHROPIC_API_KEY")
AI_RATE_PER_SEC = float(os.getenv("AI_RATE_PER_SEC", "0.5"))  # 1 call / 2s sustained
AI_RATE_BURST = float(os.getenv("AI_RATE_BURST", "3"))
JOURNAL_BACKEND = os.getenv("JOURNAL_BACKEND", "sqlite").lower()
JOURNAL_DB = os.getenv("JOURNAL_DB", "steelmind.db")
JOURNAL_DSN = env_or_file("JOURNAL_DSN")  # postgres-only
JOURNAL_KEEP_TRANSITIONS = int(os.getenv("JOURNAL_KEEP_TRANSITIONS", "5000"))
JOURNAL_KEEP_AI = int(os.getenv("JOURNAL_KEEP_AI", "1000"))
JOURNAL_PRUNE_INTERVAL_SEC = float(os.getenv("JOURNAL_PRUNE_INTERVAL_SEC", "60"))
# Comma-separated list of allowed origins. Default "*" — wildcard origin
# without credentials, which is spec-valid and what a public demo wants.
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
# Operational tunables — chosen for a single-robot demo; bump for fleet use.
MAX_REQUEST_BYTES = int(os.getenv("MAX_REQUEST_BYTES", str(64 * 1024)))  # 64 KiB
WS_HEARTBEAT_SEC = float(os.getenv("WS_HEARTBEAT_SEC", "20"))
WS_HEARTBEAT_TIMEOUT_SEC = float(os.getenv("WS_HEARTBEAT_TIMEOUT_SEC", "60"))
AI_TIMEOUT_SEC = float(os.getenv("AI_TIMEOUT_SEC", "20"))
ROBOT_CONFIG = os.getenv("ROBOT_CONFIG", "backend/configs/sim_humanoid.json")
HARDWARE_WATCHDOG_SEC = float(os.getenv("HARDWARE_WATCHDOG_SEC", "2.0"))


class ConnectionManager:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        await self.attach(ws)

    async def attach(self, ws: WebSocket) -> None:
        """Register an already-accepted socket. Used by the auth-gated /ws
        endpoint where accept() must run before the token check."""
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
        if not targets:
            return
        # Fan out in parallel so one slow client doesn't delay the broadcast
        # cadence for everyone else. Failures are collected and the dead
        # sockets removed after the send wave completes. Re-raise
        # CancelledError so shutdown isn't masked by a stuck client.
        results = await asyncio.gather(
            *(ws.send_text(message) for ws in targets), return_exceptions=True
        )
        for ws, result in zip(targets, results, strict=True):
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, Exception):
                await self.disconnect(ws)

    @property
    def count(self) -> int:
        return len(self._clients)


def snapshot_to_sensor(snapshot) -> SensorData:
    """Project a HAL snapshot into the wire-format SensorData the WS clients
    already consume. Joint names that aren't in the snapshot just don't
    appear in joint_positions — RobotScene.tsx tolerates missing joints."""
    ori = snapshot.imu.orientation
    ang = snapshot.imu.angular_velocity
    acc = snapshot.imu.linear_acceleration
    return SensorData(
        imu_orientation=Vector3(x=ori[0], y=ori[1], z=ori[2]),
        imu_angular_velocity=Vector3(x=ang[0], y=ang[1], z=ang[2]),
        imu_linear_acceleration=Vector3(x=acc[0], y=acc[1], z=acc[2]),
        joint_positions={n: js.position for n, js in snapshot.joints.items()},
        joint_velocities={n: js.velocity for n, js in snapshot.joints.items()},
        battery_voltage=snapshot.battery_voltage,
        battery_percent=snapshot.battery_percent,
    )


AI_LATENCY_BUCKETS_MS = (50, 100, 250, 500, 1000, 2000, 5000, 10000)


class Metrics:
    """Tiny counter+histogram set rendered as Prometheus text on /metrics."""

    def __init__(self) -> None:
        self.transitions_total = 0
        self.ai_commands_total = 0
        self.ai_repairs_total = 0
        self.ai_errors_total = 0
        self.rate_limited_total = 0
        self.sensor_frames_total = 0
        # AI latency histogram: cumulative counts per upper bound (ms).
        self._latency_bucket_counts = [0] * len(AI_LATENCY_BUCKETS_MS)
        self._latency_overflow = 0
        self._latency_sum_ms = 0.0
        self._latency_count = 0

    def observe_ai_latency_ms(self, ms: float) -> None:
        self._latency_sum_ms += ms
        self._latency_count += 1
        for i, upper in enumerate(AI_LATENCY_BUCKETS_MS):
            if ms <= upper:
                self._latency_bucket_counts[i] += 1
                return
        self._latency_overflow += 1

    def _histogram_lines(self) -> list[str]:
        lines = [
            "# HELP steelmind_ai_latency_ms AI commander translate() wall time.",
            "# TYPE steelmind_ai_latency_ms histogram",
        ]
        cumulative = 0
        for i, upper in enumerate(AI_LATENCY_BUCKETS_MS):
            cumulative += self._latency_bucket_counts[i]
            lines.append(f'steelmind_ai_latency_ms_bucket{{le="{upper}"}} {cumulative}')
        cumulative += self._latency_overflow
        lines.append(f'steelmind_ai_latency_ms_bucket{{le="+Inf"}} {cumulative}')
        lines.append(f"steelmind_ai_latency_ms_sum {self._latency_sum_ms:.3f}")
        lines.append(f"steelmind_ai_latency_ms_count {self._latency_count}")
        return lines

    def render(self, *, ws_clients: int, ai_history: int, ai_sessions: int) -> str:
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
            "# HELP steelmind_ai_history Total AI conversation memory turns across sessions.",
            "# TYPE steelmind_ai_history gauge",
            f"steelmind_ai_history {ai_history}",
            "# HELP steelmind_ai_sessions Distinct AI conversation sessions.",
            "# TYPE steelmind_ai_sessions gauge",
            f"steelmind_ai_sessions {ai_sessions}",
            *self._histogram_lines(),
            "",
        ]
        return "\n".join(lines)


def _build_journal() -> JournalBase:
    """Resolve which journal backend to use based on JOURNAL_BACKEND env.

    Default is SQLite for zero-config demos. Set JOURNAL_BACKEND=postgres
    and JOURNAL_DSN=postgresql://... in any multi-replica deployment so
    every replica shares the same event history."""
    if JOURNAL_BACKEND == "postgres":
        if not JOURNAL_DSN:
            raise RuntimeError(
                "JOURNAL_BACKEND=postgres requires JOURNAL_DSN (or JOURNAL_DSN_FILE)"
            )
        # Late import keeps asyncpg optional for the SQLite default.
        from .journal_postgres import PostgresJournal

        return PostgresJournal(JOURNAL_DSN)
    if JOURNAL_BACKEND not in ("sqlite", ""):
        raise RuntimeError(f"unknown JOURNAL_BACKEND: {JOURNAL_BACKEND!r}")
    return Journal(JOURNAL_DB)


class AppContext:
    def __init__(self) -> None:
        self.state_machine = StateMachine()
        self.manager = ConnectionManager()
        self.ai = AICommander(api_key=ANTHROPIC_API_KEY, timeout_sec=AI_TIMEOUT_SEC)
        # Marks the app as ready (lifespan started) vs alive (process up).
        # Liveness flips False on shutdown so /readyz returns 503 and load
        # balancers stop sending traffic during drain.
        self.ready = False
        # Per-client last-pong timestamps for the heartbeat sweeper.
        self.ws_last_seen: dict[WebSocket, float] = {}
        self.ai_rate = TokenBucket(rate_per_sec=AI_RATE_PER_SEC, burst=AI_RATE_BURST)
        # Journal construction is deferred to start() so a misconfigured
        # JOURNAL_BACKEND doesn't break module import — error surfaces at
        # lifespan startup where it can be logged and reported via /readyz.
        self.journal: JournalBase | None = None
        self.metrics = Metrics()
        self.background_tasks: set[asyncio.Task[None]] = set()
        self.current_tree: BehaviorTree | None = None
        self.behavior_lock = asyncio.Lock()
        # Hardware + trajectory player. Built in start() so config load /
        # bus open failures hit the lifespan handler with a real log line
        # instead of breaking module import.
        self.hardware: RobotHardware | None = None
        self.current_behavior_task: asyncio.Task[None] | None = None
        self.watchdog: Watchdog | None = None
        self._sensor_task: asyncio.Task[None] | None = None
        self._transition_task: asyncio.Task[None] | None = None
        self._prune_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.journal = _build_journal()
        await self.journal.init()
        joints = load_config(ROBOT_CONFIG)
        self.hardware = build_hardware(joints)
        await self.hardware.init()
        # The watchdog fires HAL.estop() if the sensor loop stops feeding
        # it — covers a hung asyncio loop, a deadlocked bus thread, or a
        # crashed pytest fixture leaking past lifespan.
        self.watchdog = Watchdog(
            expire_seconds=HARDWARE_WATCHDOG_SEC, on_expire=self.hardware.estop
        )
        self.watchdog.start()
        self._sensor_task = asyncio.create_task(self._sensor_loop())
        self._transition_task = asyncio.create_task(self._transition_loop())
        self._prune_task = asyncio.create_task(self._prune_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self.ready = True

    async def stop(self) -> None:
        # Flip readiness first so a load balancer's next /readyz probe pulls
        # us out of rotation before we start tearing things down. uvicorn
        # itself owns the WS close on shutdown — it sends close code 1012
        # ("service restart") which is the standard signal for clients to
        # back off and reconnect. We don't try to compete with that
        # ordering by sending our own close frame; the readiness flip plus
        # /readyz returning 503 is the production-correct signaling path.
        self.ready = False
        # Drain background plan executors first so they don't run against a
        # half-torn-down state machine / journal.
        for bg in list(self.background_tasks):
            bg.cancel()
        for task in (
            self._sensor_task,
            self._transition_task,
            self._prune_task,
            self._heartbeat_task,
        ):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.exception("background task raised during shutdown")
        if self.current_tree:
            await self.current_tree.stop()
        if self.current_behavior_task and not self.current_behavior_task.done():
            self.current_behavior_task.cancel()
        if self.watchdog:
            await self.watchdog.stop()
        if self.hardware:
            await self.hardware.close()
        if self.journal:
            await self.journal.close()

    async def _heartbeat_loop(self) -> None:
        """Server-driven ping. Every WS_HEARTBEAT_SEC we send a {type:'ping'}
        to every client; if a client hasn't sent any frame back inside
        WS_HEARTBEAT_TIMEOUT_SEC, we evict it. Catches half-open TCP
        connections that the OS-level keepalive would only detect after
        minutes."""
        while True:
            await asyncio.sleep(WS_HEARTBEAT_SEC)
            now = time.monotonic()
            async with self.manager._lock:
                sockets = list(self.manager._clients)
            payload = json.dumps({"type": "ping"})
            for ws in sockets:
                last = self.ws_last_seen.get(ws, now)
                if now - last > WS_HEARTBEAT_TIMEOUT_SEC:
                    logger.info(
                        "evicting stale ws", extra={"idle_sec": round(now - last, 1)}
                    )
                    try:
                        await ws.close(code=1011, reason="heartbeat timeout")
                    except Exception:
                        pass
                    await self.manager.disconnect(ws)
                    self.ws_last_seen.pop(ws, None)
                    continue
                try:
                    await ws.send_text(payload)
                except Exception:
                    await self.manager.disconnect(ws)
                    self.ws_last_seen.pop(ws, None)

    async def _prune_loop(self) -> None:
        while True:
            await asyncio.sleep(JOURNAL_PRUNE_INTERVAL_SEC)
            try:
                deleted = await self.journal.prune(
                    keep_transitions=JOURNAL_KEEP_TRANSITIONS,
                    keep_ai_commands=JOURNAL_KEEP_AI,
                )
                if deleted["transitions"] or deleted["ai_commands"]:
                    logger.info("journal pruned: %s", deleted)
            except Exception:
                logger.exception("journal prune failed")

    async def _sensor_loop(self) -> None:
        period = 1.0 / SENSOR_HZ
        while True:
            try:
                assert self.hardware is not None
                snapshot = await self.hardware.read()
                if self.watchdog:
                    self.watchdog.feed()
                data = snapshot_to_sensor(snapshot)
                await self.manager.broadcast(SensorEvent(data=data))
                self.metrics.sensor_frames_total += 1
            except Exception:
                # A flaky read can't take down the loop — log once and
                # keep cycling so the watchdog gets to make the decision.
                logger.exception("sensor loop iteration failed")
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

# OpenTelemetry: wired before the middleware stack so spans cover everything.
# No-op when OTEL_EXPORTER_OTLP_ENDPOINT is unset.
configure_tracing(app)

# Order matters: outermost runs first per request.
# 1) RequestIdMiddleware tags every request and logs it (so the size-limit
#    rejection below still appears in the access log under a tagged id).
# 2) RequestSizeLimitMiddleware rejects oversized bodies BEFORE the route
#    handler touches them, so a 100 MB payload can't allocate that much
#    memory inside the worker.
# 3) CORSMiddleware handles preflight and tags responses.
app.add_middleware(RequestIdMiddleware)
app.add_middleware(RequestSizeLimitMiddleware, max_bytes=MAX_REQUEST_BYTES)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    # Wildcard origin + credentials is invalid per CORS spec — browsers reject
    # it. Enable credentials only when a concrete origin list is configured.
    allow_credentials=CORS_ORIGINS != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _session_key(request: Request) -> str:
    sid = request.headers.get("x-session-id")
    if sid:
        return sid[:64]  # opaque; clamp length to prevent memory abuse
    return request.client.host if request.client else "default"


@app.get("/health")
async def health() -> dict:
    """Full-fat health/inventory endpoint. Used by /health-style consumers
    (the frontend) that want the operational details in one call.
    For k8s-style probes prefer /livez and /readyz."""
    return {
        "ok": True,
        "state": ctx.state_machine.state.value,
        "clients": ctx.manager.count,
        "ai_enabled": ctx.ai.enabled,
        "ai_history": ctx.ai.history_length(),
        "ai_sessions": ctx.ai.session_count,
        "auth_required": auth_enabled(),
        "ready": ctx.ready,
        "time": datetime.now(UTC).isoformat(),
    }


@app.get("/livez", include_in_schema=False)
async def livez() -> Response:
    """Liveness probe — cheap, returns 200 as long as the process loop is
    answering. A liveness probe failing means k8s restarts the pod."""
    return Response(content="ok", media_type="text/plain")


@app.get("/readyz", include_in_schema=False)
async def readyz() -> Response:
    """Readiness probe — 200 only when lifespan startup has completed and
    shutdown hasn't started. A failing readiness probe makes k8s stop
    routing traffic without restarting the pod, which is exactly what we
    want during a graceful shutdown."""
    if not ctx.ready:
        return Response(content="draining", media_type="text/plain", status_code=503)
    return Response(content="ready", media_type="text/plain")


@app.post("/ai-reset", dependencies=[Depends(require_admin)])
async def ai_reset(request: Request) -> dict:
    sid = request.headers.get("x-session-id")
    ctx.ai.reset_history(sid[:64] if sid else None)
    return {"ok": True, "ai_history": ctx.ai.history_length()}


@app.post("/estop", dependencies=[Depends(require_operator)])
async def estop() -> dict:
    """Latching emergency stop. Cancels any active behavior, force-transitions
    to IDLE, and cuts torque via the hardware. Subsequent writes are silently
    dropped until /estop/clear runs."""
    if ctx.current_behavior_task and not ctx.current_behavior_task.done():
        ctx.current_behavior_task.cancel()
    if ctx.hardware:
        await ctx.hardware.estop()
    await ctx.state_machine.transition(RobotState.IDLE, reason="estop", force=True)
    ctx.state_machine.set_behavior(None)
    ctx.state_machine.set_error("estop latched")
    return {"ok": True, "estopped": True}


@app.post("/estop/clear", dependencies=[Depends(require_admin)])
async def estop_clear() -> dict:
    """Operator-initiated reset. Admin-only — clearing an E-stop should
    require human acknowledgement, not be reachable from a stuck script."""
    if ctx.hardware:
        await ctx.hardware.clear_estop()
    ctx.state_machine.set_error(None)
    return {"ok": True, "estopped": False}


@app.get("/metrics")
async def metrics() -> Response:
    body = ctx.metrics.render(
        ws_clients=ctx.manager.count,
        ai_history=ctx.ai.history_length(),
        ai_sessions=ctx.ai.session_count,
    )
    return Response(content=body, media_type="text/plain; version=0.0.4")


# Journal endpoints carry user-supplied text (AI prompts) and full transition
# history. /counts is just integers so it's safe to leave open for monitoring;
# the row-level endpoints require auth when API_TOKEN is set.
@app.get("/journal/transitions", dependencies=[Depends(require_viewer)])
async def journal_transitions(limit: int = 100) -> dict:
    return {"transitions": await ctx.journal.list_transitions(limit=min(limit, 1000))}


@app.get("/journal/ai-commands", dependencies=[Depends(require_viewer)])
async def journal_ai_commands(limit: int = 100) -> dict:
    return {"ai_commands": await ctx.journal.list_ai_commands(limit=min(limit, 1000))}


@app.get("/journal/counts")
async def journal_counts() -> dict:
    return await ctx.journal.counts()


@app.get("/status")
async def status() -> dict:
    return ctx.state_machine.status.model_dump()


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


@app.post("/command", response_model=CommandResponse, dependencies=[Depends(require_operator)])
async def command(req: CommandRequest) -> CommandResponse:
    return await _dispatch_command(req)


async def _play_trajectory(behavior_name: str) -> None:
    """Background task: sample the behavior's trajectory at SENSOR_HZ and
    push each waypoint through the HAL. Returns the state machine to
    STANDING on normal completion. Cancellable — _run_behavior cancels the
    in-flight task when a new behavior preempts."""
    assert ctx.hardware is not None
    behavior = BEHAVIORS[behavior_name]
    traj = behavior.build()
    period = 1.0 / SENSOR_HZ
    started = time.monotonic()
    try:
        await ctx.state_machine.transition(
            RobotState.EXECUTING, reason=f"behavior:{behavior_name}", force=True
        )
        ctx.state_machine.set_behavior(behavior_name)
        while True:
            t = time.monotonic() - started
            targets = traj.sample(t)
            await ctx.hardware.write(targets)
            if t >= traj.duration:
                break
            await asyncio.sleep(period)
    except asyncio.CancelledError:
        # Preempted by a newer behavior. Caller handles state cleanup.
        raise
    finally:
        ctx.state_machine.set_behavior(None)
        if ctx.state_machine.state == RobotState.EXECUTING:
            try:
                await ctx.state_machine.transition(
                    RobotState.STANDING, reason=f"behavior:{behavior_name}:done", force=True
                )
            except Exception:
                logger.exception("post-behavior transition failed")


async def _run_behavior(name: str) -> None:
    """Replace any running behavior with a fresh one. The HTTP route awaits
    the EXECUTING transition before returning so the response carries the
    real new state, but the trajectory itself plays in the background."""
    async with ctx.behavior_lock:
        prev = ctx.current_behavior_task
        if prev and not prev.done():
            prev.cancel()
            try:
                await prev
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("previous behavior task raised on cancel")
        if ctx.hardware:
            await ctx.hardware.enable()
        task = asyncio.create_task(_play_trajectory(name))
        ctx.current_behavior_task = task
        # Wait briefly for the player to commit the EXECUTING transition.
        for _ in range(50):
            if (
                ctx.state_machine.state == RobotState.EXECUTING
                and ctx.state_machine.status.current_behavior == name
            ):
                break
            await asyncio.sleep(0.01)


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
    params: dict = Field(default_factory=dict)
    executed: bool
    detail: str | None = None


class AICommandResponse(BaseModel):
    explanation: str
    steps: list[AIPlanStepResult]
    fully_executed: bool
    repaired: bool = False


@app.post(
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

    client_key = request.client.host if request.client else "unknown"
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


async def _execute_plan(steps: list[PlanStep]) -> None:
    for step in steps:
        try:
            await _dispatch_command(CommandRequest(command=step.command, params=step.params))
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
    # Accept the upgrade first so we can send a structured close on auth fail.
    await ws.accept()
    role = await require_token_ws(ws, min_role=Role.OPERATOR)
    if role is None:
        return
    # require_token_ws didn't close → connection is authorized. Register
    # without re-accepting.
    await ctx.manager.attach(ws)
    ctx.ws_last_seen[ws] = time.monotonic()
    try:
        await ws.send_text(StatusEvent(status=ctx.state_machine.status).model_dump_json())
        while True:
            raw = await ws.receive_text()
            ctx.ws_last_seen[ws] = time.monotonic()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_text(json.dumps({"type": "error", "detail": "invalid json"}))
                continue
            await _handle_ws_message(ws, msg)
    except WebSocketDisconnect:
        pass
    finally:
        ctx.ws_last_seen.pop(ws, None)
        await ctx.manager.disconnect(ws)


async def _handle_ws_message(ws: WebSocket, msg: dict) -> None:
    kind = msg.get("type")
    if kind == "ping":
        await ws.send_text(json.dumps({"type": "pong"}))
    elif kind == "pong":
        # Client-side heartbeat echo. last_seen is already updated by the
        # outer receive loop, so we don't need to send anything back.
        return
    elif kind == "command":
        try:
            req = CommandRequest(**msg.get("payload", {}))
            resp = await _dispatch_command(req)
            await ws.send_text(resp.model_dump_json())
        except HTTPException as e:
            await ws.send_text(json.dumps({"type": "error", "detail": e.detail}))
    else:
        await ws.send_text(json.dumps({"type": "error", "detail": f"unknown message: {kind}"}))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
