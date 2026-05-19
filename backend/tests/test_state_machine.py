import asyncio

import pytest

from backend.models import RobotState
from backend.state_machine import InvalidTransitionError, StateMachine


@pytest.mark.asyncio
async def test_initial_state_is_idle() -> None:
    sm = StateMachine()
    assert sm.state == RobotState.IDLE
    assert sm.status.previous_state is None


@pytest.mark.asyncio
async def test_valid_transition_chain() -> None:
    sm = StateMachine()
    await sm.transition(RobotState.STANDING)
    assert sm.state == RobotState.STANDING
    await sm.transition(RobotState.WALKING)
    assert sm.state == RobotState.WALKING
    assert sm.status.previous_state == RobotState.STANDING


@pytest.mark.asyncio
async def test_invalid_transition_rejected() -> None:
    sm = StateMachine()
    with pytest.raises(InvalidTransitionError):
        await sm.transition(RobotState.WALKING)  # IDLE -> WALKING is invalid


@pytest.mark.asyncio
async def test_force_overrides_validation() -> None:
    sm = StateMachine()
    await sm.transition(RobotState.WALKING, force=True)
    assert sm.state == RobotState.WALKING


@pytest.mark.asyncio
async def test_subscribers_receive_events() -> None:
    sm = StateMachine()
    queue = sm.subscribe()
    await sm.transition(RobotState.STANDING, reason="test")
    event = await asyncio.wait_for(queue.get(), timeout=1)
    assert event.from_state == RobotState.IDLE
    assert event.to_state == RobotState.STANDING
    assert event.reason == "test"


@pytest.mark.asyncio
async def test_self_transition_is_noop() -> None:
    sm = StateMachine()
    event = await sm.transition(RobotState.IDLE)
    assert event.reason == "noop"
    assert sm.state == RobotState.IDLE


@pytest.mark.asyncio
async def test_invalid_walking_to_idle_direct() -> None:
    # WALKING cannot transition directly to IDLE (must go via STANDING).
    sm = StateMachine()
    await sm.transition(RobotState.STANDING)
    await sm.transition(RobotState.WALKING)
    with pytest.raises(InvalidTransitionError):
        await sm.transition(RobotState.IDLE)


@pytest.mark.asyncio
async def test_set_behavior_and_error() -> None:
    sm = StateMachine()
    sm.set_behavior("wave")
    assert sm.status.current_behavior == "wave"
    sm.set_error("imu fault")
    assert sm.status.error == "imu fault"
    sm.set_behavior(None)
    assert sm.status.current_behavior is None
