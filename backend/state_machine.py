from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from .models import RobotState, RobotStatus, StateTransitionEvent

VALID_TRANSITIONS: dict[RobotState, set[RobotState]] = {
    RobotState.IDLE: {RobotState.STANDING, RobotState.EXECUTING},
    RobotState.STANDING: {RobotState.IDLE, RobotState.WALKING, RobotState.EXECUTING},
    RobotState.WALKING: {RobotState.STANDING, RobotState.EXECUTING},
    RobotState.EXECUTING: {RobotState.IDLE, RobotState.STANDING, RobotState.WALKING},
}


class InvalidTransitionError(Exception):
    pass


class StateMachine:
    def __init__(self, initial: RobotState = RobotState.IDLE) -> None:
        self._status = RobotStatus(state=initial)
        self._lock = asyncio.Lock()
        self._listeners: list[asyncio.Queue[StateTransitionEvent]] = []

    @property
    def status(self) -> RobotStatus:
        return self._status.model_copy()

    @property
    def state(self) -> RobotState:
        return self._status.state

    def subscribe(self) -> asyncio.Queue[StateTransitionEvent]:
        queue: asyncio.Queue[StateTransitionEvent] = asyncio.Queue(maxsize=64)
        self._listeners.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[StateTransitionEvent]) -> None:
        if queue in self._listeners:
            self._listeners.remove(queue)

    async def transition(
        self, target: RobotState, *, reason: str | None = None, force: bool = False
    ) -> StateTransitionEvent:
        async with self._lock:
            current = self._status.state
            if target == current:
                event = StateTransitionEvent(
                    from_state=current, to_state=target, reason=reason or "noop"
                )
                return event
            if not force and target not in VALID_TRANSITIONS.get(current, set()):
                raise InvalidTransitionError(
                    f"Cannot transition from {current.value} to {target.value}"
                )
            self._status = RobotStatus(
                state=target,
                previous_state=current,
                current_behavior=self._status.current_behavior,
                last_transition=datetime.now(UTC),
            )
            event = StateTransitionEvent(from_state=current, to_state=target, reason=reason)

        await self._broadcast(event)
        return event

    async def set_behavior(self, name: str | None) -> None:
        async with self._lock:
            self._status = self._status.model_copy(update={"current_behavior": name})

    async def set_error(self, error: str | None) -> None:
        async with self._lock:
            self._status = self._status.model_copy(update={"error": error})

    async def _broadcast(self, event: StateTransitionEvent) -> None:
        for queue in list(self._listeners):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass
