from __future__ import annotations

import os
from pathlib import Path


def env_or_file(name: str, default: str | None = None) -> str | None:
    """Read a secret from ${NAME}, or fall back to the file at ${NAME}_FILE.

    Matches the convention used by Docker secrets, k8s secret mounts, and
    twelve-factor sidecars — pass the literal value via env for dev, mount a
    file in prod and point the *_FILE var at it.

    Trailing whitespace from the file (e.g. trailing newline written by
    `echo`) is stripped so callers can do safe equality checks."""
    value = os.getenv(name)
    if value:
        return value
    file_path = os.getenv(f"{name}_FILE")
    if file_path:
        try:
            return Path(file_path).read_text(encoding="utf-8").strip()
        except OSError:
            return default
    return default
