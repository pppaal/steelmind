import pytest

from backend.journal import Journal


@pytest.mark.asyncio
async def test_prune_keeps_only_n_most_recent() -> None:
    j = Journal(":memory:")
    for i in range(20):
        await j.record_transition("IDLE", "STANDING", f"r{i}")
    deleted = await j.prune(keep_transitions=5, keep_ai_commands=5)
    assert deleted["transitions"] == 15
    rows = await j.list_transitions(limit=100)
    assert len(rows) == 5
    # Most recent first; r19 is the last insert.
    assert rows[0]["reason"] == "r19"
    assert rows[-1]["reason"] == "r15"


@pytest.mark.asyncio
async def test_prune_noop_when_under_cap() -> None:
    j = Journal(":memory:")
    await j.record_ai_command("hi", {"steps": []}, "hi")
    deleted = await j.prune(keep_transitions=100, keep_ai_commands=100)
    assert deleted == {"transitions": 0, "ai_commands": 0}
