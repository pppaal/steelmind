import pytest

from backend.behaviors import BEHAVIOR_DESCRIPTIONS, BEHAVIORS
from backend.models import RobotState
from backend.state_machine import StateMachine


def test_registry_keys_match_descriptions() -> None:
    assert set(BEHAVIORS.keys()) == set(BEHAVIOR_DESCRIPTIONS.keys())
    assert "demo" in BEHAVIORS


@pytest.mark.asyncio
async def test_each_behavior_factory_constructs_tree() -> None:
    sm = StateMachine()
    for name, factory in BEHAVIORS.items():
        tree = factory(sm)
        assert tree.root.name == name


@pytest.mark.asyncio
async def test_demo_runs_and_ends_in_standing() -> None:
    sm = StateMachine()
    tree = BEHAVIORS["demo"](sm)
    task = tree.start()
    await task
    assert sm.state == RobotState.STANDING
    assert sm.status.current_behavior is None
