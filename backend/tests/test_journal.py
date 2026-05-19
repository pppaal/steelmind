import pytest

from backend.journal import Journal


@pytest.mark.asyncio
async def test_init_and_record() -> None:
    j = Journal(":memory:")
    await j.init()
    await j.record_transition("IDLE", "STANDING", "test")
    await j.record_transition("STANDING", "WALKING", None)
    rows = await j.list_transitions()
    assert len(rows) == 2
    assert rows[0]["from_state"] == "STANDING"  # most recent first
    assert rows[1]["reason"] == "test"


@pytest.mark.asyncio
async def test_ai_command_round_trip() -> None:
    j = Journal(":memory:")
    await j.record_ai_command(
        text="일어서",
        plan={"steps": [{"command": "stand", "params": {}}], "explanation": "일어선다"},
        explanation="일어선다",
        repaired=True,
    )
    rows = await j.list_ai_commands()
    assert len(rows) == 1
    assert rows[0]["repaired"] is True
    assert rows[0]["plan"]["steps"][0]["command"] == "stand"


@pytest.mark.asyncio
async def test_counts() -> None:
    j = Journal(":memory:")
    await j.record_transition("IDLE", "STANDING", None)
    await j.record_ai_command(text="x", plan={"steps": []}, explanation="x")
    counts = await j.counts()
    assert counts == {"transitions": 1, "ai_commands": 1}
