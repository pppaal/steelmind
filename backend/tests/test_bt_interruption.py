"""BehaviorTree.stop() must interrupt in-flight Actions, not wait for the
current asyncio.sleep to finish on its own."""

import asyncio
import time

import pytest

from backend.behavior_tree import Action, BehaviorTree, NodeStatus, Sequence


@pytest.mark.asyncio
async def test_stop_interrupts_long_sleep_quickly() -> None:
    async def slow() -> NodeStatus:
        # If stop() can't cancel, this 5-second sleep blocks stop() for 5s.
        await asyncio.sleep(5)
        return NodeStatus.SUCCESS

    tree = BehaviorTree(Sequence("s", [Action("slow", slow)]))
    tree.start()
    await asyncio.sleep(0.05)

    started = time.monotonic()
    await tree.stop()
    elapsed = time.monotonic() - started

    assert elapsed < 0.5, f"stop() took {elapsed:.2f}s — BT not actually interruptible"
    assert not tree.is_running


@pytest.mark.asyncio
async def test_wait_after_stop_is_fast() -> None:
    """A caller using wait() after stop() should also return immediately
    rather than blocking on the cancelled action."""

    async def slow() -> NodeStatus:
        await asyncio.sleep(5)
        return NodeStatus.SUCCESS

    tree = BehaviorTree(Action("slow", slow))
    tree.start()
    await asyncio.sleep(0.05)

    await tree.stop()
    started = time.monotonic()
    await tree.wait()
    assert time.monotonic() - started < 0.05


@pytest.mark.asyncio
async def test_natural_completion_still_works() -> None:
    """The cancellation path must not break the normal completion path."""

    async def fast() -> NodeStatus:
        return NodeStatus.SUCCESS

    tree = BehaviorTree(Sequence("s", [Action("a", fast), Action("b", fast)]))
    task = tree.start()
    await task
    assert tree.last_status == NodeStatus.SUCCESS
    assert not tree.is_running
