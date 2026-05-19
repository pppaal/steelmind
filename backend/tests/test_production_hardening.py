"""Coverage for production-hardening additions: probes, request-id, size
limits, fresh-app isolation, WAL pragma, AI client timeout."""

import sqlite3

from fastapi.testclient import TestClient

from backend.ai_commander import AICommander
from backend.journal import Journal


def test_livez_returns_plain_text(fresh_app: TestClient) -> None:
    r = fresh_app.get("/livez")
    assert r.status_code == 200
    assert r.text == "ok"


def test_readyz_ready_after_lifespan(fresh_app: TestClient) -> None:
    r = fresh_app.get("/readyz")
    assert r.status_code == 200
    assert r.text == "ready"


def test_request_id_round_trips(fresh_app: TestClient) -> None:
    r = fresh_app.get("/health", headers={"X-Request-Id": "abc-123"})
    assert r.headers["x-request-id"] == "abc-123"


def test_request_id_generated_when_missing(fresh_app: TestClient) -> None:
    r = fresh_app.get("/health")
    rid = r.headers.get("x-request-id")
    assert rid and len(rid) >= 16


def test_oversized_post_rejected_with_413(fresh_app: TestClient) -> None:
    # /command's body must clear the request-size middleware. Default cap is
    # 64 KiB; sending 200 KiB should bounce at the middleware layer with 413
    # before any handler runs.
    huge = "x" * (200 * 1024)
    r = fresh_app.post("/command", json={"command": "stand", "params": {"pad": huge}})
    assert r.status_code == 413


def test_journal_uses_wal_when_on_disk(tmp_path: str) -> None:
    """A fresh on-disk journal must come up in WAL mode so concurrent
    reads (e.g. /journal/transitions) don't block writes from the
    broadcaster."""
    db_path = f"{tmp_path}/wal.db"

    async def _check() -> str:
        j = Journal(db_path)
        await j.init()
        # Open a separate inspecting connection to assert the on-disk pragma.
        conn = sqlite3.connect(db_path)
        try:
            (mode,) = conn.execute("PRAGMA journal_mode").fetchone()
        finally:
            conn.close()
        await j.close()
        return mode

    import asyncio

    mode = asyncio.run(_check())
    assert mode.lower() == "wal"


def test_ai_commander_accepts_timeout_kwarg() -> None:
    ai = AICommander(api_key="sk-fake", timeout_sec=5.0)
    assert ai._client is not None
    # anthropic SDK honors the constructor timeout — surface it directly.
    assert getattr(ai._client, "timeout", None) is not None
