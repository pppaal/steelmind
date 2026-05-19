from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import ClassVar


class JsonFormatter(logging.Formatter):
    """Single-line JSON per record. Stable schema for log aggregators."""

    _RESERVED: ClassVar[set[str]] = {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "message", "asctime", "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "t": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Surface any structured extras passed via logger.info(..., extra={...}).
        for key, value in record.__dict__.items():
            if key in self._RESERVED or key.startswith("_"):
                continue
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                value = repr(value)
            payload[key] = value
        return json.dumps(payload, ensure_ascii=False)


def configure(level: str | int = "INFO", *, json_logs: bool | None = None) -> None:
    """Idempotent root logger setup. JSON in production, plaintext in TTY by default."""
    if json_logs is None:
        env = os.getenv("LOG_FORMAT", "").lower()
        if env in {"json", "1", "true"}:
            json_logs = True
        elif env in {"text", "plain", "0", "false"}:
            json_logs = False
        else:
            json_logs = not sys.stderr.isatty()

    formatter: logging.Formatter
    if json_logs:
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s | %(message)s")

    def _install(target_logger: logging.Logger) -> None:
        for h in list(target_logger.handlers):
            target_logger.removeHandler(h)
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        target_logger.addHandler(handler)
        target_logger.setLevel(level)

    # Root catches our own loggers and any libraries that propagate.
    _install(logging.getLogger())
    # Uvicorn ships with its own handlers + propagate=True; attach our
    # formatter directly and disable propagation so lines aren't doubled.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.propagate = False
        _install(lg)
