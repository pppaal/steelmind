import pytest

from backend import ai_commander
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


def test_sessions_are_capped_lru(monkeypatch) -> None:
    monkeypatch.setattr(ai_commander, "MAX_SESSIONS", 3)
    ai = AICommander(api_key=None)
    for s in ("a", "b", "c"):
        ai._bucket(s)
    # Touch "a" so it's most-recently-used; "b" is now the LRU.
    ai._bucket("a")
    ai._bucket("d")  # exceeds cap → evicts the LRU ("b")
    assert ai.session_count == 3
    assert set(ai._history.keys()) == {"c", "a", "d"}
    assert "b" not in ai._history  # the LRU session was evicted
