"""Command signing + replay protection for the live WebSocket control channel.

Each command may carry (ts, nonce, sig) where sig = HMAC-SHA256(key, canonical)
and key is the connection's auth token (the shared secret both ends already
hold). The server rejects a command whose signature is wrong, whose timestamp
is outside a skew window, or whose nonce has been seen before — so a captured
control frame can't be replayed to move the robot. Pure/stdlib; enforcement is
opt-in (REQUIRE_SIGNED_COMMANDS) and only possible when auth is configured."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections import OrderedDict


def canonical(command: str, params: dict, ts: float, nonce: str) -> str:
    """Stable serialization signed by both ends. params is key-sorted so the
    client and server agree regardless of dict ordering."""
    body = json.dumps(params or {}, sort_keys=True, separators=(",", ":"))
    return f"{ts}:{nonce}:{command}:{body}"


def sign(key: str, command: str, params: dict, ts: float, nonce: str) -> str:
    msg = canonical(command, params, ts, nonce).encode("utf-8")
    return hmac.new(key.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def verify(key: str, sig: str, command: str, params: dict, ts: float, nonce: str) -> bool:
    expected = sign(key, command, params, ts, nonce)
    return hmac.compare_digest(expected, sig or "")


class NonceCache:
    """Bounded set of recently-seen nonces (insertion-ordered, LRU-evicted).
    seen() records the nonce and returns whether it was already present."""

    def __init__(self, capacity: int = 8192) -> None:
        self._capacity = capacity
        self._seen: OrderedDict[str, None] = OrderedDict()

    def seen(self, nonce: str) -> bool:
        if nonce in self._seen:
            return True
        self._seen[nonce] = None
        while len(self._seen) > self._capacity:
            self._seen.popitem(last=False)
        return False
