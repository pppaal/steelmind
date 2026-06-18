"""Application context: the FastAPI app, the long-lived AppContext singleton,
its background loops, and the small infrastructure helpers shared by routes.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from ..ai_commander import AICommander
from ..calibration import Calibration
from ..connection_manager import ConnectionManager
from ..hardware import RobotHardware, build_hardware
from ..hardware.base import JointSpec
from ..journal import Journal
from ..journal_base import JournalBase
from ..keyframes import KeyframeStore
from ..kinematics import PlanarChain
from ..metrics import Metrics
from ..middleware import RequestIdMiddleware, RequestSizeLimitMiddleware
from ..models import RobotState, SensorData, SensorEvent, StatusEvent, Vector3
from ..rate_limit import TokenBucket
from ..robot_config import load_chain, load_config
from ..routines import RoutineStore
from ..safety import Watchdog, overloaded_joints
from ..state_machine import StateMachine
from ..tracing import configure as configure_tracing
from . import config
from .config import (
    AI_RATE_BURST,
    AI_RATE_PER_SEC,
    AI_TIMEOUT_SEC,
    ANTHROPIC_API_KEY,
    CALIBRATION_FILE,
    CORS_ORIGINS,
    DEADMAN_REQUIRED,
    DEADMAN_TIMEOUT_SEC,
    EFFORT_OVERLOAD_FRAMES,
    EFFORT_PROTECTION,
    HARDWARE_WATCHDOG_SEC,
    JOURNAL_BACKEND,
    JOURNAL_DB,
    JOURNAL_DSN,
    JOURNAL_KEEP_AI,
    JOURNAL_KEEP_TRANSITIONS,
    JOURNAL_PRUNE_INTERVAL_SEC,
    KEYFRAMES_FILE,
    MAX_REQUEST_BYTES,
    ROBOT_CONFIG,
    ROUTINES_FILE,
    SENSOR_HZ,
    WS_HEARTBEAT_SEC,
    WS_HEARTBEAT_TIMEOUT_SEC,
    logger,
)


def _apply_calibration(joints: list[JointSpec], calib: Calibration) -> list[JointSpec]:
    """Fold runtime calibration offsets on top of each joint's config offset.

    JointSpec is frozen, so we return fresh specs. The HAL only ever sees
    the combined offset, keeping calibration transparent to the drivers."""
    return [
        dataclasses.replace(j, offset=j.offset + calib.offset_for(j.name))
        for j in joints
    ]


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
        joint_efforts={n: js.effort for n, js in snapshot.joints.items()},
        battery_voltage=snapshot.battery_voltage,
        battery_percent=snapshot.battery_percent,
    )


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
        from ..journal_postgres import PostgresJournal

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
        # Per-joint consecutive-overload frame counters for protective stop.
        self._overload_counts: dict[str, int] = {}
        # Deadman: monotonic deadline; motion is permitted while now < this.
        self._deadman_until: float = 0.0
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
                await self._check_overload(snapshot)
                await self._check_deadman()
                data = snapshot_to_sensor(snapshot)
                await self.manager.broadcast(SensorEvent(data=data))
                self.metrics.sensor_frames_total += 1
            except Exception:
                # A flaky read can't take down the loop — log once and
                # keep cycling so the watchdog gets to make the decision.
                logger.exception("sensor loop iteration failed")
            await asyncio.sleep(period)

    async def _check_overload(self, snapshot) -> None:
        """Trip a protective stop when a joint sustains effort above its
        configured max_effort. Requires EFFORT_OVERLOAD_FRAMES consecutive
        over-limit frames so a single transient spike doesn't cut motion."""
        if not EFFORT_PROTECTION or snapshot.estopped:
            self._overload_counts.clear()
            return
        specs = {j.name: j for j in self.joints}
        efforts = {n: js.effort for n, js in snapshot.joints.items()}
        over = set(overloaded_joints(efforts, specs))
        # Drop counters for joints no longer over-limit.
        for name in [n for n in self._overload_counts if n not in over]:
            del self._overload_counts[name]
        tripped: list[str] = []
        for name in over:
            self._overload_counts[name] = self._overload_counts.get(name, 0) + 1
            if self._overload_counts[name] >= EFFORT_OVERLOAD_FRAMES:
                tripped.append(name)
        if tripped:
            await self.protective_stop(f"overload: {', '.join(sorted(tripped))}")

    async def protective_stop(self, reason: str) -> None:
        """Latching, hardware-level stop triggered by a safety reflex (e.g.
        overload). Mirrors the operator E-stop: cancels motion, cuts torque,
        drops to IDLE, and latches an error that requires /estop/clear."""
        logger.warning("protective stop: %s", reason)
        self.metrics.overload_stops_total += 1
        self._overload_counts.clear()
        if self.routine_task and not self.routine_task.done():
            self.routine_task.cancel()
        if self.current_behavior_task and not self.current_behavior_task.done():
            self.current_behavior_task.cancel()
        if self.hardware:
            await self.hardware.estop()
        await self.state_machine.transition(RobotState.IDLE, reason=reason, force=True)
        await self.state_machine.set_behavior(None)
        await self.state_machine.set_error(reason)

    # --- Deadman / hold-to-enable -------------------------------------------
    def refresh_deadman(self) -> None:
        """Extend the deadman deadline — called for each hold ping the operator
        sends over /ws."""
        self._deadman_until = time.monotonic() + DEADMAN_TIMEOUT_SEC

    def deadman_ok(self) -> bool:
        """True when motion is permitted: either the deadman isn't required or
        the operator is currently holding the enable control."""
        if not DEADMAN_REQUIRED:
            return True
        return time.monotonic() < self._deadman_until

    def _motion_active(self) -> bool:
        return bool(
            (self.current_behavior_task and not self.current_behavior_task.done())
            or (self.routine_task and not self.routine_task.done())
        )

    async def _check_deadman(self) -> None:
        """Freeze any in-flight motion if the deadman hold lapses. Unlike a
        protective stop this doesn't latch — it just cancels the active motion
        (the HAL holds the last commanded pose); re-holding re-arms motion."""
        if not DEADMAN_REQUIRED or self.deadman_ok():
            return
        if not self._motion_active():
            return
        logger.warning("deadman released — freezing motion")
        self.metrics.deadman_stops_total += 1
        if self.routine_task and not self.routine_task.done():
            self.routine_task.cancel()
        if self.current_behavior_task and not self.current_behavior_task.done():
            self.current_behavior_task.cancel()

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


def _client_ip(request: Request) -> str:
    """Best-effort client IP for rate limiting / session fallback.

    Honours X-Forwarded-For only when TRUST_PROXY_HEADERS is set, taking the
    left-most (original client) entry. Without that flag the header is
    attacker-controlled, so we fall back to the raw socket peer. Read through
    the config module so a runtime monkeypatch is honoured.
    """
    if config.TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            first = forwarded.split(",")[0].strip()
            if first:
                return first
    return request.client.host if request.client else "unknown"


def _session_key(request: Request) -> str:
    sid = request.headers.get("x-session-id")
    if sid:
        return sid[:64]  # opaque; clamp length to prevent memory abuse
    return _client_ip(request)


# Names become dict keys persisted to JSON; restrict them to a sane charset so
# a client can't inject control chars / absurd lengths into the store.
_NAME_RE = re.compile(r"^[A-Za-z0-9 _-]{1,64}$")


def _validate_name(name: str, kind: str) -> None:
    if not _NAME_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail=(
                f"invalid {kind} name: 1-64 chars of letters, digits, space, "
                "underscore or hyphen only"
            ),
        )


def require_deadman() -> None:
    """Reject a motion request when the deadman is required but not currently
    held. A no-op unless DEADMAN_REQUIRED is set."""
    if not ctx.deadman_ok():
        raise HTTPException(
            status_code=423,
            detail="deadman not held — hold the enable control to move",
        )
