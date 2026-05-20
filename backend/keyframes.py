"""Teach-and-repeat: named joint poses captured at runtime, composable into
a replayable trajectory.

Workflow on a real robot:
  1. torque off (the bring-up tool / a future UI toggle) and pose by hand
  2. POST /keyframes/{name} to capture the current joint positions
  3. repeat for each waypoint
  4. POST /keyframes/play {names:[...]} to replay them as smooth motion

Poses persist to JSON so a taught routine survives a restart.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from .trajectory import Trajectory, compose, hold, min_jerk

Pose = dict[str, float]


class KeyframeStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._frames: dict[str, Pose] = {}
        self._lock = asyncio.Lock()

    @property
    def names(self) -> list[str]:
        return list(self._frames)

    def get(self, name: str) -> Pose | None:
        frame = self._frames.get(name)
        return dict(frame) if frame is not None else None

    def all(self) -> dict[str, Pose]:
        return {k: dict(v) for k, v in self._frames.items()}

    async def load(self) -> None:
        async with self._lock:
            self._frames = await asyncio.to_thread(self._load_sync)

    def _load_sync(self) -> dict[str, Pose]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        out: dict[str, Pose] = {}
        for name, pose in data.get("frames", {}).items():
            out[str(name)] = {str(j): float(v) for j, v in pose.items()}
        return out

    async def record(self, name: str, pose: Pose) -> None:
        async with self._lock:
            self._frames[name] = dict(pose)
            await asyncio.to_thread(self._save_sync)

    async def delete(self, name: str) -> bool:
        async with self._lock:
            existed = self._frames.pop(name, None) is not None
            if existed:
                await asyncio.to_thread(self._save_sync)
            return existed

    def _save_sync(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps({"frames": self._frames}, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def build_trajectory(
        self, names: list[str], segment_duration: float, start_pose: Pose | None = None
    ) -> Trajectory:
        """Compose a min-jerk trajectory through the named keyframes.

        If start_pose is given, the first segment eases from there into the
        first keyframe so playback doesn't jerk from wherever the robot
        currently sits. A short hold caps the end so the final pose settles."""
        missing = [n for n in names if n not in self._frames]
        if missing:
            raise KeyError(f"unknown keyframes: {missing}")
        if not names:
            raise ValueError("no keyframes to play")

        poses = [self._frames[n] for n in names]
        segments: list[Trajectory] = []
        prev = start_pose if start_pose is not None else poses[0]
        for pose in poses:
            segments.append(min_jerk(prev, pose, duration=segment_duration))
            prev = pose
        segments.append(hold(prev, duration=0.3))
        return compose(*segments)
