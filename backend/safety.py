"""Safety primitives used by the HAL.

Clamping and slewing are correctness layers — never trust a behavior to
respect joint limits, always clamp at the boundary. The watchdog is the
liveness layer: if the read loop stops feeding it, motors get cut."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from .hardware.base import JointSpec


def clamp_targets(
    targets: dict[str, float], joints: dict[str, JointSpec]
) -> tuple[dict[str, float], list[str]]:
    """Return a copy of targets with each value clamped to the joint's soft
    limits, plus the names of joints that actually got clamped."""
    out: dict[str, float] = {}
    clamped: list[str] = []
    for name, value in targets.items():
        spec = joints.get(name)
        if spec is None:
            # Drop unknown joints rather than letting them through. A
            # behavior that thinks it can move "left_pinkie_tip" on a robot
            # without one shouldn't cause an exception, just a no-op.
            continue
        new = spec.clamp(value)
        if new != value:
            clamped.append(name)
        out[name] = new
    return out, clamped


def overloaded_joints(
    efforts: dict[str, float], joints: dict[str, JointSpec]
) -> list[str]:
    """Names of joints whose measured effort exceeds their max_effort.

    Joints with max_effort <= 0 have protection disabled and are never
    reported. Pure function so the protective-stop policy can be unit-tested
    without a running event loop."""
    over: list[str] = []
    for name, effort in efforts.items():
        spec = joints.get(name)
        if spec is None or spec.max_effort <= 0:
            continue
        if effort > spec.max_effort:
            over.append(name)
    return over


def slew_toward(
    current: dict[str, float],
    target: dict[str, float],
    joints: dict[str, JointSpec],
    dt: float,
) -> dict[str, float]:
    """Rate-limited approach: move each joint at most max_velocity * dt
    radians per call. Returns the new positions."""
    out = dict(current)
    for name, want in target.items():
        spec = joints.get(name)
        if spec is None:
            continue
        have = current.get(name, 0.0)
        max_step = spec.max_velocity * dt
        delta = want - have
        if abs(delta) > max_step:
            delta = max_step if delta > 0 else -max_step
        out[name] = have + delta
    return out


class Watchdog:
    """Heartbeat-based safety timer. Each successful HAL.read() pets the dog
    via feed(); if expire_seconds passes without a feed, the bound callback
    fires (typically HAL.estop)."""

    def __init__(self, expire_seconds: float, on_expire: Callable[[], Awaitable[None]]) -> None:
        self.expire_seconds = expire_seconds
        self._on_expire = on_expire
        self._last_feed = time.monotonic()
        self._task: asyncio.Task[None] | None = None
        self._fired = False

    def feed(self) -> None:
        self._last_feed = time.monotonic()
        self._fired = False

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        # Sleep in short slices so cancellation is responsive.
        while True:
            await asyncio.sleep(self.expire_seconds / 4)
            if self._fired:
                continue
            if time.monotonic() - self._last_feed > self.expire_seconds:
                self._fired = True
                try:
                    await self._on_expire()
                except Exception:
                    # Log via the caller's logger — we don't have one here.
                    pass
