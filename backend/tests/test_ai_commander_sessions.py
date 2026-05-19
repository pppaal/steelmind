import pytest

from backend.ai_commander import AICommander, AICommanderError
from backend.models import RobotStatus


@pytest.mark.asyncio
async def test_disabled_without_key() -> None:
    ai = AICommander(api_key=None)
    assert not ai.enabled
    with pytest.raises(AICommanderError):
        await ai.translate("stand", RobotStatus())


def test_per_session_isolation() -> None:
    ai = AICommander(api_key=None)
    ai._bucket("a").append(("hi from a", {"steps": [], "explanation": ""}))
    ai._bucket("b").append(("hi from b", {"steps": [], "explanation": ""}))
    assert ai.history_length("a") == 1
    assert ai.history_length("b") == 1
    assert ai.history_length() == 2
    assert ai.session_count == 2


def test_reset_targets_one_session() -> None:
    ai = AICommander(api_key=None)
    ai._bucket("a").append(("x", {}))
    ai._bucket("b").append(("y", {}))
    ai.reset_history("a")
    assert ai.history_length("a") == 0
    assert ai.history_length("b") == 1


def test_reset_all_with_none() -> None:
    ai = AICommander(api_key=None)
    ai._bucket("a").append(("x", {}))
    ai._bucket("b").append(("y", {}))
    ai.reset_history(None)
    assert ai.session_count == 0
