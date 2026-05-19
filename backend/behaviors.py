from __future__ import annotations

import asyncio
from collections.abc import Callable

from .behavior_tree import Action, BehaviorTree, NodeStatus, Sequence
from .models import RobotState
from .state_machine import StateMachine

BehaviorFactory = Callable[[StateMachine], BehaviorTree]


def _enter(sm: StateMachine, name: str) -> Action:
    async def _tick() -> NodeStatus:
        await sm.transition(RobotState.EXECUTING, reason=f"behavior:{name}", force=True)
        sm.set_behavior(name)
        return NodeStatus.SUCCESS

    return Action(f"{name}/enter", _tick)


def _exit(sm: StateMachine, name: str, target: RobotState = RobotState.STANDING) -> Action:
    async def _tick() -> NodeStatus:
        sm.set_behavior(None)
        await sm.transition(target, reason=f"behavior:{name}:done", force=True)
        return NodeStatus.SUCCESS

    return Action(f"{name}/exit", _tick)


def _wait(name: str, seconds: float) -> Action:
    async def _tick() -> NodeStatus:
        await asyncio.sleep(seconds)
        return NodeStatus.SUCCESS

    return Action(f"{name}/wait:{seconds}", _tick)


def demo(sm: StateMachine) -> BehaviorTree:
    n = "demo"
    return BehaviorTree(Sequence(n, [_enter(sm, n), _wait(n, 1.5), _exit(sm, n)]))


def wave(sm: StateMachine) -> BehaviorTree:
    n = "wave"
    return BehaviorTree(Sequence(n, [_enter(sm, n), _wait(n, 3.0), _exit(sm, n)]))


def squat(sm: StateMachine) -> BehaviorTree:
    n = "squat"
    return BehaviorTree(Sequence(n, [_enter(sm, n), _wait(n, 4.0), _exit(sm, n)]))


def patrol(sm: StateMachine) -> BehaviorTree:
    n = "patrol"
    return BehaviorTree(
        Sequence(
            n,
            [
                _enter(sm, n),
                _wait(n, 2.5),
                _wait(n, 2.5),
                _exit(sm, n),
            ],
        )
    )


def dance(sm: StateMachine) -> BehaviorTree:
    n = "dance"
    return BehaviorTree(Sequence(n, [_enter(sm, n), _wait(n, 5.0), _exit(sm, n)]))


BEHAVIORS: dict[str, BehaviorFactory] = {
    "demo": demo,
    "wave": wave,
    "squat": squat,
    "patrol": patrol,
    "dance": dance,
}


BEHAVIOR_DESCRIPTIONS: dict[str, str] = {
    "demo": "기본 시연. 1.5초 EXECUTING 후 STANDING 복귀.",
    "wave": "오른팔을 들어 좌우로 흔든다. 3초.",
    "squat": "무릎과 엉덩이를 굽혀 앉았다 일어선다. 4초.",
    "patrol": "제자리에서 정찰 보행. 5초.",
    "dance": "팔과 다리를 함께 흔드는 댄스. 5초.",
}
