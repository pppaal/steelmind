"""Routine macros: named sequences of steps that script the robot's
existing primitives (command / behavior / keyframes / reach / wait).

The store only persists raw step dicts — validation lives in main.py via
Pydantic models so the schema shows up in OpenAPI. Persisted to JSON so a
taught routine survives a restart.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

Step = dict[str, object]


class RoutineStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._routines: dict[str, list[Step]] = {}
        self._lock = asyncio.Lock()

    @property
    def names(self) -> list[str]:
        return list(self._routines)

    def get(self, name: str) -> list[Step] | None:
        steps = self._routines.get(name)
        return [dict(s) for s in steps] if steps is not None else None

    def all(self) -> dict[str, list[Step]]:
        return {k: [dict(s) for s in v] for k, v in self._routines.items()}

    async def load(self) -> None:
        async with self._lock:
            self._routines = await asyncio.to_thread(self._load_sync)

    def _load_sync(self) -> dict[str, list[Step]]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        out: dict[str, list[Step]] = {}
        for name, steps in data.get("routines", {}).items():
            if isinstance(steps, list):
                out[str(name)] = [dict(s) for s in steps if isinstance(s, dict)]
        return out

    async def save(self, name: str, steps: list[Step]) -> None:
        async with self._lock:
            self._routines[name] = [dict(s) for s in steps]
            await asyncio.to_thread(self._save_sync)

    async def delete(self, name: str) -> bool:
        async with self._lock:
            existed = self._routines.pop(name, None) is not None
            if existed:
                await asyncio.to_thread(self._save_sync)
            return existed

    def _save_sync(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps({"routines": self._routines}, indent=2), encoding="utf-8")
        tmp.replace(self.path)
