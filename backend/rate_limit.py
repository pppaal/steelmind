from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    updated: float


class TokenBucket:
    """Simple async token-bucket rate limiter, keyed by an arbitrary identity
    (typically the client IP). Designed for low-throughput protection of
    expensive endpoints like /ai-command rather than DDoS mitigation."""

    def __init__(self, rate_per_sec: float, burst: float) -> None:
        self.rate = rate_per_sec
        self.burst = burst
        # Initialize new buckets with updated=0 so the first allow() sees
        # arbitrarily large elapsed time and the min() clamps tokens to burst.
        self._buckets: dict[str, _Bucket] = defaultdict(lambda: _Bucket(burst, 0.0))
        self._lock = asyncio.Lock()

    async def allow(self, key: str) -> tuple[bool, float]:
        """Returns (allowed, retry_after_seconds)."""
        async with self._lock:
            now = time.monotonic()
            bucket = self._buckets[key]
            elapsed = now - bucket.updated
            bucket.tokens = min(self.burst, bucket.tokens + elapsed * self.rate)
            bucket.updated = now
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return True, 0.0
            needed = 1.0 - bucket.tokens
            return False, needed / self.rate
