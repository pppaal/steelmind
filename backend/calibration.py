"""Per-joint calibration persistence.

A calibration is a map joint_name → offset_radians. It's applied on top of
the static offset baked into the robot config, so an operator can re-zero a
joint at runtime (via /calibration) without editing the config file or
re-mounting the servo horn. Saved to a JSON file so it survives restarts.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path


class Calibration:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._offsets: dict[str, float] = {}
        self._lock = asyncio.Lock()

    @property
    def offsets(self) -> dict[str, float]:
        return dict(self._offsets)

    def offset_for(self, joint: str) -> float:
        return self._offsets.get(joint, 0.0)

    async def load(self) -> None:
        async with self._lock:
            self._offsets = await asyncio.to_thread(self._load_sync)

    def _load_sync(self) -> dict[str, float]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return {str(k): float(v) for k, v in data.get("offsets", {}).items()}

    async def set_offset(self, joint: str, offset_rad: float) -> None:
        async with self._lock:
            self._offsets[joint] = float(offset_rad)
            await asyncio.to_thread(self._save_sync)

    async def set_many(self, offsets: dict[str, float]) -> None:
        async with self._lock:
            for joint, value in offsets.items():
                self._offsets[joint] = float(value)
            await asyncio.to_thread(self._save_sync)

    async def clear(self) -> None:
        async with self._lock:
            self._offsets = {}
            await asyncio.to_thread(self._save_sync)

    def _save_sync(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: temp file + rename so a crash mid-write can't leave
        # a truncated calibration that the next boot would silently load.
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps({"offsets": self._offsets}, indent=2), encoding="utf-8")
        tmp.replace(self.path)
