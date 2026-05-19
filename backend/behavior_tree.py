from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from enum import Enum


class NodeStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    RUNNING = "RUNNING"


TickFn = Callable[[], Awaitable[NodeStatus]]


class Node(ABC):
    name: str = "node"

    @abstractmethod
    async def tick(self) -> NodeStatus: ...


class Action(Node):
    def __init__(self, name: str, fn: TickFn) -> None:
        self.name = name
        self._fn = fn

    async def tick(self) -> NodeStatus:
        return await self._fn()


class Condition(Node):
    def __init__(self, name: str, predicate: Callable[[], Awaitable[bool] | bool]) -> None:
        self.name = name
        self._predicate = predicate

    async def tick(self) -> NodeStatus:
        result = self._predicate()
        if asyncio.iscoroutine(result):
            result = await result
        return NodeStatus.SUCCESS if result else NodeStatus.FAILURE


class Sequence(Node):
    def __init__(self, name: str, children: list[Node]) -> None:
        self.name = name
        self.children = children

    async def tick(self) -> NodeStatus:
        for child in self.children:
            status = await child.tick()
            if status != NodeStatus.SUCCESS:
                return status
        return NodeStatus.SUCCESS


class Selector(Node):
    def __init__(self, name: str, children: list[Node]) -> None:
        self.name = name
        self.children = children

    async def tick(self) -> NodeStatus:
        for child in self.children:
            status = await child.tick()
            if status != NodeStatus.FAILURE:
                return status
        return NodeStatus.FAILURE


class Parallel(Node):
    def __init__(self, name: str, children: list[Node], success_threshold: int | None = None) -> None:
        self.name = name
        self.children = children
        self.success_threshold = success_threshold or len(children)

    async def tick(self) -> NodeStatus:
        results = await asyncio.gather(*(c.tick() for c in self.children))
        successes = sum(1 for r in results if r == NodeStatus.SUCCESS)
        failures = sum(1 for r in results if r == NodeStatus.FAILURE)
        if successes >= self.success_threshold:
            return NodeStatus.SUCCESS
        if failures > len(self.children) - self.success_threshold:
            return NodeStatus.FAILURE
        return NodeStatus.RUNNING


class BehaviorTree:
    def __init__(self, root: Node, tick_rate_hz: float = 10.0) -> None:
        self.root = root
        self.tick_period = 1.0 / tick_rate_hz
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self.last_status: NodeStatus | None = None

    async def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self.last_status = await self.root.tick()
                if self.last_status != NodeStatus.RUNNING:
                    break
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.tick_period)
                except TimeoutError:
                    continue
        except asyncio.CancelledError:
            # External stop() cancelled the in-flight tick. Treat as cleanly
            # interrupted; let the surrounding orchestrator do post-cancel
            # state cleanup. Do not re-raise — _run is the task body itself
            # and re-raising would mark the task as cancelled even when the
            # caller is awaiting it after stop().
            self.last_status = NodeStatus.FAILURE

    def start(self) -> asyncio.Task[None]:
        if self._task and not self._task.done():
            return self._task
        self._stop.clear()
        self._task = asyncio.create_task(self._run())
        return self._task

    async def stop(self) -> None:
        # Setting the event alone only signals between ticks; if the current
        # tick is blocked inside an Action (e.g. asyncio.sleep in a wait
        # node), it won't observe _stop until the action returns naturally.
        # Cancel the task so the in-flight await is interrupted right now.
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def wait(self) -> NodeStatus | None:
        if self._task is None:
            return self.last_status
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        return self.last_status
