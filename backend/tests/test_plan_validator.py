from backend.ai_commander import PlanStep
from backend.models import RobotState
from backend.plan_validator import validate_plan


def step(cmd: str, **params: object) -> PlanStep:
    return PlanStep(command=cmd, params=dict(params))


def test_valid_single_step() -> None:
    ok, err = validate_plan([step("stand")], RobotState.IDLE)
    assert ok and err is None


def test_invalid_idle_to_walk_direct() -> None:
    ok, err = validate_plan([step("walk")], RobotState.IDLE)
    assert not ok
    assert err is not None
    assert "IDLE -> WALKING" in err


def test_repair_path_via_stand() -> None:
    ok, err = validate_plan([step("stand"), step("walk")], RobotState.IDLE)
    assert ok and err is None


def test_multi_step_with_execute() -> None:
    plan = [step("stand"), step("execute", behavior="wave")]
    ok, err = validate_plan(plan, RobotState.IDLE)
    assert ok and err is None


def test_unknown_behavior_flagged() -> None:
    ok, err = validate_plan([step("execute", behavior="moonwalk")], RobotState.STANDING)
    assert not ok
    assert "moonwalk" in (err or "")


def test_self_transition_ok() -> None:
    ok, err = validate_plan([step("stand")], RobotState.STANDING)
    assert ok and err is None
