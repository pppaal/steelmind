"""Coverage for the small audit-pass fixes."""

import pytest

from backend.ai_commander import AICommanderError, AIPlanResult, PlanStep
from backend.main import AIPlanStepResult


def test_plan_first_raises_on_empty() -> None:
    # The tool schema is supposed to enforce minItems=1, but we defensively
    # raise instead of IndexError so the surrounding endpoint can catch a
    # single AICommanderError type.
    result = AIPlanResult(steps=[], explanation="empty")
    with pytest.raises(AICommanderError):
        _ = result.first


def test_plan_first_returns_first_step() -> None:
    result = AIPlanResult(
        steps=[PlanStep(command="stand"), PlanStep(command="walk")],
        explanation="ok",
    )
    assert result.first.command == "stand"


def test_ai_plan_step_result_params_default_is_fresh_dict() -> None:
    """Pydantic v2 already isolates mutable defaults via the default_factory,
    but enforce that two independent instances don't share state."""
    a = AIPlanStepResult(command="stand", executed=False)
    b = AIPlanStepResult(command="stand", executed=False)
    a.params["x"] = 1
    assert "x" not in b.params
