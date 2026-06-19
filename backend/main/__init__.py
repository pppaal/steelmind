"""steelmind backend application package.

`backend.main:app` remains the ASGI entrypoint (uvicorn target). The module
that used to be a single 1200-line file is split into:

  config        — environment-derived settings + logging
  schemas       — request/response + routine-step pydantic models
  context       — FastAPI app, AppContext singleton, background loops, helpers
  motion        — command/behavior/keyframe/reach/routine/plan execution
  routes_*      — APIRouters grouped by concern, included below

Names previously importable from ``backend.main`` are re-exported here so
existing imports (and tests) keep working.
"""

from __future__ import annotations

from ..connection_manager import ConnectionManager
from ..metrics import AI_LATENCY_BUCKETS_MS, Metrics
from . import config
from .config import (
    MAX_JOG_RAD,
    MAX_ROUTINE_STEPS,
    TRUST_PROXY_HEADERS,
    logger,
)
from .context import (
    AppContext,
    _apply_calibration,
    _build_journal,
    _client_ip,
    _session_key,
    _validate_name,
    app,
    ctx,
    lifespan,
    snapshot_to_sensor,
)
from .motion import (
    _await_motion,
    _coerce_routine,
    _dispatch_command,
    _execute_plan,
    _play,
    _run_behavior,
    _run_routine,
    _validate_routine_steps,
)
from .routes_ai import router as _ai_router
from .routes_camera import router as _camera_router
from .routes_control import router as _control_router
from .routes_demos import router as _demos_router
from .routes_foxglove import router as _foxglove_router
from .routes_health import router as _health_router
from .routes_motion import router as _motion_router
from .routes_recording import router as _recording_router
from .routes_routines import router as _routines_router
from .routes_sim import router as _sim_router
from .routes_ws import router as _ws_router
from .schemas import (
    AICommandRequest,
    AICommandResponse,
    AIPlanStepResult,
    AIRoutineRequest,
    BehaviorStep,
    CalibrationRequest,
    CommandStep,
    JogRequest,
    KeyframePlayRequest,
    KeyframesStep,
    ReachRequest,
    ReachStep,
    RoutineBody,
    RoutineStep,
    WaitStep,
)

# Register routes. Order across routers doesn't affect matching here; within a
# router declaration order is preserved (e.g. /keyframes/play before
# /keyframes/{name} in routes_motion).
for _router in (
    _health_router,
    _control_router,
    _motion_router,
    _routines_router,
    _ai_router,
    _camera_router,
    _recording_router,
    _demos_router,
    _sim_router,
    _foxglove_router,
    _ws_router,
):
    app.include_router(_router)

__all__ = [
    "AI_LATENCY_BUCKETS_MS",
    "MAX_JOG_RAD",
    "MAX_ROUTINE_STEPS",
    "TRUST_PROXY_HEADERS",
    "AICommandRequest",
    "AICommandResponse",
    "AIPlanStepResult",
    "AIRoutineRequest",
    "AppContext",
    "BehaviorStep",
    "CalibrationRequest",
    "CommandStep",
    "ConnectionManager",
    "JogRequest",
    "KeyframePlayRequest",
    "KeyframesStep",
    "Metrics",
    "ReachRequest",
    "ReachStep",
    "RoutineBody",
    "RoutineStep",
    "WaitStep",
    "_apply_calibration",
    "_await_motion",
    "_build_journal",
    "_client_ip",
    "_coerce_routine",
    "_dispatch_command",
    "_execute_plan",
    "_play",
    "_run_behavior",
    "_run_routine",
    "_session_key",
    "_validate_name",
    "_validate_routine_steps",
    "app",
    "config",
    "ctx",
    "lifespan",
    "logger",
    "snapshot_to_sensor",
]
