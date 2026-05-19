from __future__ import annotations

from .ai_commander import PlanStep
from .behaviors import BEHAVIORS
from .models import RobotState
from .state_machine import VALID_TRANSITIONS

COMMAND_TO_STATE: dict[str, RobotState] = {
    "stand": RobotState.STANDING,
    "walk": RobotState.WALKING,
    "idle": RobotState.IDLE,
    "stop": RobotState.STANDING,
}


def validate_plan(
    steps: list[PlanStep], current_state: RobotState
) -> tuple[bool, str | None]:
    """Dry-run the plan against the state machine's transition table.

    Returns (ok, error_message). An error string is suitable for feeding back
    into the AI commander as repair context."""
    state = current_state
    errors: list[str] = []

    for i, step in enumerate(steps):
        cmd = step.command.lower()
        if cmd == "execute":
            behavior = step.params.get("behavior", "demo")
            if behavior not in BEHAVIORS:
                errors.append(f"step {i + 1}: unknown behavior '{behavior}'")
                continue
            # execute can fire from any state (we force-transition); skip state check.
            state = RobotState.EXECUTING
            continue

        target = COMMAND_TO_STATE.get(cmd)
        if target is None:
            errors.append(f"step {i + 1}: unknown command '{cmd}'")
            continue

        if target == state:
            continue

        if target not in VALID_TRANSITIONS.get(state, set()):
            errors.append(
                f"step {i + 1}: {state.value} -> {target.value} is not a valid transition"
            )
            continue

        state = target

    if errors:
        return False, "; ".join(errors)
    return True, None
