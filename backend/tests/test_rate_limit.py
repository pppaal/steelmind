import asyncio

import pytest

from backend.rate_limit import TokenBucket


@pytest.mark.asyncio
async def test_burst_then_block() -> None:
    bucket = TokenBucket(rate_per_sec=1.0, burst=3)
    a1, _ = await bucket.allow("k")
    a2, _ = await bucket.allow("k")
    a3, _ = await bucket.allow("k")
    a4, wait = await bucket.allow("k")
    assert (a1, a2, a3) == (True, True, True)
    assert a4 is False
    assert wait > 0


@pytest.mark.asyncio
async def test_independent_keys() -> None:
    bucket = TokenBucket(rate_per_sec=1.0, burst=1)
    a, _ = await bucket.allow("a")
    b, _ = await bucket.allow("b")
    assert a and b
    a2, _ = await bucket.allow("a")
    assert a2 is False


@pytest.mark.asyncio
async def test_refill_over_time() -> None:
    bucket = TokenBucket(rate_per_sec=100.0, burst=1)
    ok, _ = await bucket.allow("k")
    assert ok
    blocked, _ = await bucket.allow("k")
    assert not blocked
    await asyncio.sleep(0.03)
    ok2, _ = await bucket.allow("k")
    assert ok2
