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
from typing import Annotated, Literal

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
from .calibration import Calibration
from .hardware import RobotHardware, build_hardware
from .hardware.base import JointSpec
from .journal import Journal
from .journal_base import JournalBase
from .keyframes import KeyframeStore
from .kinematics import PlanarChain
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
from .robot_config import load_chain, load_config
from .routines import RoutineStore
from .safety import Watchdog
from .secrets import env_or_file
from .state_machine import InvalidTransitionError, StateMachine
from .tracing import configure as configure_tracing
from .trajectory import Trajectory, min_jerk

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
CALIBRATION_FILE = os.getenv("CALIBRATION_FILE", "calibration.json")
KEYFRAMES_FILE = os.getenv("KEYFRAMES_FILE", "keyframes.json")
KEYFRAME_SEGMENT_SEC = float(os.getenv("KEYFRAME_SEGMENT_SEC", "1.5"))
ROUTINES_FILE = os.getenv("ROUTINES_FILE", "routines.json")
# Largest single jog step a /jog call may request, radians. Keeps a fat-
# fingered operator from commanding a 180° slam in one click.
MAX_JOG_RAD = float(os.getenv("MAX_JOG_RAD", "0.35"))  # ~20 degrees


import dataclasses  # noqa: E402 - grouped with the helper that uses it


def _apply_calibration(joints: list[JointSpec], calib: Calibration) -> list[JointSpec]:
    """Fold runtime calibration offsets on top of each joint's config offset.

    JointSpec is frozen, so we return fresh specs. The HAL only ever sees
    the combined offset, keeping calibration transparent to the drivers."""
    return [
        dataclasses.replace(j, offset=j.offset + calib.offset_for(j.name))
        for j in joints
    ]


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
        self.joints: list[JointSpec] = []
        self.chain: PlanarChain | None = None
        self.calibration = Calibration(CALIBRATION_FILE)
        self.keyframes = KeyframeStore(KEYFRAMES_FILE)
        self.routines = RoutineStore(ROUTINES_FILE)
        self.routine_task: asyncio.Task[None] | None = None
        self.current_behavior_task: asyncio.Task[None] | None = None
        self.watchdog: Watchdog | None = None
        self._sensor_task: asyncio.Task[None] | None = None
        self._transition_task: asyncio.Task[None] | None = None
        self._prune_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.journal = _build_journal()
        await self.journal.init()
        await self.calibration.load()
        await self.keyframes.load()
        await self.routines.load()
        self.joints = _apply_calibration(load_config(ROBOT_CONFIG), self.calibration)
        self.chain = load_chain(ROBOT_CONFIG)
        self.hardware = build_hardware(self.joints)
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
    ctx.state_machine.set_behavior(None)
    ctx.state_machine.set_error("estop latched")
    return {"ok": True, "estopped": True}


class JogRequest(BaseModel):
    joint: str
    delta: float  # radians, relative to current target


@app.post("/jog", dependencies=[Depends(require_operator)])
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


@app.get("/calibration", dependencies=[Depends(require_viewer)])
async def get_calibration() -> dict:
    return {"offsets": ctx.calibration.offsets}


class CalibrationRequest(BaseModel):
    offsets: dict[str, float]


@app.post("/calibration", dependencies=[Depends(require_admin)])
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
        ctx.state_machine.set_behavior(label)
        while True:
            t = time.monotonic() - started
            await ctx.hardware.write(traj.sample(t))
            if t >= traj.duration:
                break
            await asyncio.sleep(period)
    except asyncio.CancelledError:
        raise
    finally:
        ctx.state_machine.set_behavior(None)
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


@app.get("/behaviors")
async def list_behaviors() -> dict:
    return {
        "behaviors": [
            {"name": name, "description": BEHAVIOR_DESCRIPTIONS.get(name, "")}
            for name in BEHAVIORS
        ]
    }


@app.get("/keyframes", dependencies=[Depends(require_viewer)])
async def list_keyframes() -> dict:
    return {"keyframes": ctx.keyframes.all()}


class KeyframePlayRequest(BaseModel):
    names: list[str]
    segment_duration: float | None = None


# NOTE: this literal route MUST be declared before /keyframes/{name} or the
# parameterized route shadows it (matching name="play").
@app.post("/keyframes/play", dependencies=[Depends(require_operator)])
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
    await _play(f"keyframes:{'+'.join(req.names)}", traj)
    return {"ok": True, "names": req.names, "duration": traj.duration}


@app.post("/keyframes/{name}", dependencies=[Depends(require_operator)])
async def record_keyframe(name: str) -> dict:
    """Capture the current joint positions under `name`. Pair with the
    bring-up tool's torque-off mode (or a future UI toggle) to teach poses
    by hand."""
    if ctx.hardware is None:
        raise HTTPException(status_code=503, detail="hardware not ready")
    snapshot = await ctx.hardware.read()
    pose = {n: js.position for n, js in snapshot.joints.items()}
    await ctx.keyframes.record(name, pose)
    return {"ok": True, "name": name, "pose": pose}


@app.delete("/keyframes/{name}", dependencies=[Depends(require_operator)])
async def delete_keyframe(name: str) -> dict:
    if not await ctx.keyframes.delete(name):
        raise HTTPException(status_code=404, detail=f"unknown keyframe: {name}")
    return {"ok": True, "name": name}


@app.get("/fk", dependencies=[Depends(require_viewer)])
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


class ReachRequest(BaseModel):
    x: float
    y: float
    duration: float | None = None


@app.post("/reach", dependencies=[Depends(require_operator)])
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
    await _play(f"reach:({req.x:.2f},{req.y:.2f})", traj)
    return {
        "ok": True,
        "reached": reached,
        "residual": residual,
        "angles": angles,
    }


# --- Routines: scripted sequences of the primitives above ---------------------


class CommandStep(BaseModel):
    type: Literal["command"]
    command: str
    params: dict = Field(default_factory=dict)


class BehaviorStep(BaseModel):
    type: Literal["behavior"]
    behavior: str


class KeyframesStep(BaseModel):
    type: Literal["keyframes"]
    names: list[str]


class ReachStep(BaseModel):
    type: Literal["reach"]
    x: float
    y: float


class WaitStep(BaseModel):
    type: Literal["wait"]
    seconds: float


RoutineStep = Annotated[
    CommandStep | BehaviorStep | KeyframesStep | ReachStep | WaitStep,
    Field(discriminator="type"),
]


class RoutineBody(BaseModel):
    steps: list[RoutineStep]


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


@app.get("/routines", dependencies=[Depends(require_viewer)])
async def list_routines() -> dict:
    return {"routines": ctx.routines.all()}


@app.get("/routines/{name}", dependencies=[Depends(require_viewer)])
async def get_routine(name: str) -> dict:
    """Single routine, for export/sharing. 404 if unknown."""
    steps = ctx.routines.get(name)
    if steps is None:
        raise HTTPException(status_code=404, detail=f"unknown routine: {name}")
    return {"name": name, "steps": steps}


@app.put("/routines/{name}", dependencies=[Depends(require_operator)])
async def save_routine(name: str, body: RoutineBody) -> dict:
    _validate_routine_steps(body.steps)
    await ctx.routines.save(name, [s.model_dump() for s in body.steps])
    return {"ok": True, "name": name, "steps": len(body.steps)}


@app.delete("/routines/{name}", dependencies=[Depends(require_operator)])
async def delete_routine(name: str) -> dict:
    if not await ctx.routines.delete(name):
        raise HTTPException(status_code=404, detail=f"unknown routine: {name}")
    return {"ok": True, "name": name}


@app.post("/routines/{name}/run", dependencies=[Depends(require_operator)])
async def run_routine(name: str) -> dict:
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


class AIRoutineRequest(BaseModel):
    text: str
    name: str
    run: bool = False


@app.post("/ai-routine", dependencies=[Depends(require_operator)])
async def ai_routine(req: AIRoutineRequest, request: Request) -> dict:
    """Natural language → a saved routine. The AI composes loosely-typed
    steps; we validate them strictly with the routine step models (one
    repair retry on failure), save under `name`, and optionally run."""
    if not ctx.ai.enabled:
        raise HTTPException(status_code=503, detail="AI commander disabled (no ANTHROPIC_API_KEY)")
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    allowed, retry_after = await ctx.ai_rate.allow(request.client.host if request.client else "?")
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
