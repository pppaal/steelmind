"""Demonstration capture for imitation learning.

Records episodes of synchronized timesteps (joint state per frame) with a
per-episode task label and success/failure flag, and exports them in a
LeRobotDataset-style schema (observation.state / action / timestamp /
episode_index / frame_index / next.done). `action` is framed as next-state
(standard for position-control behavioral cloning): action[i] = state[i+1],
with the final frame marked next.done.

State-only for now (proprioception); image observations are a follow-up.
Dependency-free — a downstream script converts the JSON export to parquet /
the HF `datasets` format for actual training (which needs a GPU; capture does
not)."""

from __future__ import annotations

from datetime import UTC, datetime


class DemoRecorder:
    def __init__(
        self,
        fps: float,
        max_frames_per_episode: int = 36000,
        max_episodes: int = 500,
    ) -> None:
        self._fps = fps
        self._max_frames = max_frames_per_episode
        self._max_episodes = max_episodes
        self._active = False
        self._task = ""
        self._started_at: str | None = None
        self._frames: list[dict[str, float]] = []  # current episode states
        self._truncated = False
        self._episodes: list[dict] = []

    @property
    def active(self) -> bool:
        return self._active

    def start(self, task: str = "") -> None:
        self._active = True
        self._task = task
        self._started_at = datetime.now(UTC).isoformat()
        self._frames = []
        self._truncated = False

    def capture(self, state: dict[str, float]) -> None:
        if not self._active:
            return
        if len(self._frames) >= self._max_frames:
            self._truncated = True
            return
        self._frames.append(dict(state))

    def stop(self, success: bool, notes: str = "") -> dict:
        if not self._active:
            return {"ok": False, "detail": "no active episode"}
        episode = {
            "episode_index": len(self._episodes),
            "task": self._task,
            "success": bool(success),
            "notes": notes,
            "started_at": self._started_at,
            "length": len(self._frames),
            "truncated": self._truncated,
            "frames": self._frames,
        }
        self._episodes.append(episode)
        # Bound memory: drop the oldest episode(s) and renumber.
        while len(self._episodes) > self._max_episodes:
            self._episodes.pop(0)
        for i, ep in enumerate(self._episodes):
            ep["episode_index"] = i
        self._active = False
        self._frames = []
        return {"ok": True, "episode_index": episode["episode_index"], "length": episode["length"]}

    def clear(self) -> None:
        self._episodes = []
        self._active = False
        self._frames = []

    def status(self) -> dict:
        return {
            "active": self._active,
            "task": self._task if self._active else None,
            "current_frames": len(self._frames) if self._active else 0,
            "episodes": len(self._episodes),
            "total_frames": sum(ep["length"] for ep in self._episodes),
            "fps": self._fps,
        }

    def episodes(self) -> list[dict]:
        """Episode metadata (no frame payloads)."""
        return [
            {k: ep[k] for k in ("episode_index", "task", "success", "length", "started_at", "truncated")}
            for ep in self._episodes
        ]

    def export(self, joint_names: list[str]) -> dict:
        """LeRobotDataset-style export. `joint_names` fixes the column order of
        the state/action vectors (missing joints → 0.0)."""
        names = list(joint_names)
        dim = len(names)
        frames: list[dict] = []
        for ep in self._episodes:
            states = [[float(s.get(n, 0.0)) for n in names] for s in ep["frames"]]
            for i, state_vec in enumerate(states):
                last = i == len(states) - 1
                frames.append({
                    "episode_index": ep["episode_index"],
                    "frame_index": i,
                    "timestamp": round(i / self._fps, 6),
                    "observation.state": state_vec,
                    # Position-control BC: next state is the action; hold on the
                    # final frame and flag done.
                    "action": states[i + 1] if not last else state_vec,
                    "next.done": last,
                    "success": ep["success"],
                })
        return {
            "fps": self._fps,
            "features": {
                "observation.state": {"dtype": "float32", "shape": [dim], "names": names},
                "action": {"dtype": "float32", "shape": [dim], "names": names},
                "timestamp": {"dtype": "float32", "shape": [1]},
                "episode_index": {"dtype": "int64", "shape": [1]},
                "frame_index": {"dtype": "int64", "shape": [1]},
                "next.done": {"dtype": "bool", "shape": [1]},
            },
            "total_episodes": len(self._episodes),
            "total_frames": len(frames),
            "episodes": self.episodes(),
            "frames": frames,
        }
