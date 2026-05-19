import asyncio

import pytest

from backend.behavior_tree import (
    Action,
    BehaviorTree,
    Condition,
    NodeStatus,
    Parallel,
    Selector,
    Sequence,
)


async def _success() -> NodeStatus:
    return NodeStatus.SUCCESS


async def _failure() -> NodeStatus:
    return NodeStatus.FAILURE


@pytest.mark.asyncio
async def test_sequence_short_circuits_on_failure() -> None:
    calls: list[str] = []

    async def a() -> NodeStatus:
        calls.append("a")
        return NodeStatus.SUCCESS

    async def b() -> NodeStatus:
        calls.append("b")
        return NodeStatus.FAILURE

    async def c() -> NodeStatus:
        calls.append("c")
        return NodeStatus.SUCCESS

    seq = Sequence("s", [Action("a", a), Action("b", b), Action("c", c)])
    assert await seq.tick() == NodeStatus.FAILURE
    assert calls == ["a", "b"]


@pytest.mark.asyncio
async def test_selector_returns_first_non_failure() -> None:
    sel = Selector("sel", [Action("f", _failure), Action("s", _success), Action("nope", _failure)])
    assert await sel.tick() == NodeStatus.SUCCESS


@pytest.mark.asyncio
async def test_parallel_threshold() -> None:
    par = Parallel(
        "p",
        [Action("a", _success), Action("b", _failure), Action("c", _success)],
        success_threshold=2,
    )
    assert await par.tick() == NodeStatus.SUCCESS


@pytest.mark.asyncio
async def test_condition_truthy() -> None:
    cond = Condition("c", lambda: True)
    assert await cond.tick() == NodeStatus.SUCCESS
    cond_async = Condition("c2", lambda: asyncio.sleep(0, result=False))
    assert await cond_async.tick() == NodeStatus.FAILURE


@pytest.mark.asyncio
async def test_behavior_tree_runs_to_completion() -> None:
    tree = BehaviorTree(Sequence("s", [Action("a", _success), Action("b", _success)]))
    task = tree.start()
    await task
    assert tree.last_status == NodeStatus.SUCCESS
    assert not tree.is_running


@pytest.mark.asyncio
async def test_behavior_tree_stop() -> None:
    async def slow() -> NodeStatus:
        await asyncio.sleep(5)
        return NodeStatus.SUCCESS

    tree = BehaviorTree(Action("slow", slow), tick_rate_hz=10)
    tree.start()
    await asyncio.sleep(0.05)
    await tree.stop()
    assert not tree.is_running
