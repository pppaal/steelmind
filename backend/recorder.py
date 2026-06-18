"""Session recorder: taps the broadcast stream into a timestamped timeline
for export (audit / time-travel debugging).

High-frequency sensor frames are skipped by default so a recording stays a
readable event log (transitions, AI commands, routine/plan progress) rather
than megabytes of telemetry. Capture is synchronous and best-effort — it
never raises into the broadcast loop and stops appending past a cap."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from pydantic import BaseModel


class SessionRecorder:
    def __init__(self, max_events: int = 5000, skip_types: tuple[str, ...] = ("sensor",)) -> None:
        self._active = False
        self._events: list[dict] = []
        self._start_mono = 0.0
        self._started_at: str | None = None
        self._max = max_events
        self._skip = set(skip_types)
        self._truncated = False

    @property
    def active(self) -> bool:
        return self._active

    @property
    def event_count(self) -> int:
        return len(self._events)

    def start(self) -> None:
        self._active = True
        self._events = []
        self._truncated = False
        self._start_mono = time.monotonic()
        self._started_at = datetime.now(UTC).isoformat()

    def stop(self) -> None:
        self._active = False

    def capture(self, payload: BaseModel | dict) -> None:
        if not self._active:
            return
        try:
            data = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else dict(payload)
        except Exception:
            return
        if data.get("type") in self._skip:
            return
        if len(self._events) >= self._max:
            self._truncated = True
            return
        self._events.append({"t": round(time.monotonic() - self._start_mono, 3), "event": data})

    def _duration(self) -> float:
        if self._active:
            return round(time.monotonic() - self._start_mono, 3)
        return self._events[-1]["t"] if self._events else 0.0

    def status(self) -> dict:
        return {
            "active": self._active,
            "count": len(self._events),
            "started_at": self._started_at,
            "duration": self._duration(),
            "truncated": self._truncated,
        }

    def export(self) -> dict:
        return {**self.status(), "events": list(self._events)}
