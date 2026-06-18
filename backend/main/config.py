"""Environment-derived configuration and logging setup.

Every tunable the backend reads from the environment lives here so the rest
of the package imports named constants instead of scattering os.getenv calls.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from ..logging_setup import configure as configure_logging
from ..secrets import env_or_file

# .env lives next to the backend package (backend/.env), one level up from
# this module (backend/main/config.py).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

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
# Upper bound on a saved routine's length. Stops a malicious/buggy client
# from persisting a 10k-step routine that DoSes the executor and broadcast.
MAX_ROUTINE_STEPS = int(os.getenv("MAX_ROUTINE_STEPS", "64"))
# Largest single jog step a /jog call may request, radians. Keeps a fat-
# fingered operator from commanding a 180° slam in one click.
MAX_JOG_RAD = float(os.getenv("MAX_JOG_RAD", "0.35"))  # ~20 degrees
# When deployed behind a reverse proxy / load balancer the TCP source IP is
# the proxy's, so per-client rate limiting collapses to a single bucket. Set
# TRUST_PROXY_HEADERS=1 *only* when a trusted proxy sets X-Forwarded-For;
# otherwise leave it off so clients can't spoof the header to dodge limits.
TRUST_PROXY_HEADERS = os.getenv("TRUST_PROXY_HEADERS", "0").lower() in ("1", "true", "yes")
