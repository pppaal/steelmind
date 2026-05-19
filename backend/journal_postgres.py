"""Postgres journal backend. Shares the JournalBase interface so it's a
drop-in replacement for the SQLite default in multi-replica deployments.

asyncpg is an optional dependency — this module only imports it on
first use so single-instance demos don't need to install it. To enable:
  pip install asyncpg
  JOURNAL_BACKEND=postgres JOURNAL_DSN=postgresql://user:pw@host/db
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from .journal_base import JournalBase

_SCHEMA = """
CREATE TABLE IF NOT EXISTS transitions (
    id          BIGSERIAL PRIMARY KEY,
    t           TIMESTAMPTZ NOT NULL,
    from_state  TEXT NOT NULL,
    to_state    TEXT NOT NULL,
    reason      TEXT
);
CREATE INDEX IF NOT EXISTS idx_transitions_t ON transitions(t DESC);

CREATE TABLE IF NOT EXISTS ai_commands (
    id          BIGSERIAL PRIMARY KEY,
    t           TIMESTAMPTZ NOT NULL,
    input       TEXT NOT NULL,
    plan        JSONB NOT NULL,
    explanation TEXT NOT NULL,
    repaired    BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_ai_commands_t ON ai_commands(t DESC);
"""


class PostgresJournal(JournalBase):
    def __init__(self, dsn: str, *, pool_min: int = 1, pool_max: int = 10) -> None:
        self.dsn = dsn
        self.pool_min = pool_min
        self.pool_max = pool_max
        self._pool: Any = None  # asyncpg.Pool, late-imported

    async def init(self) -> None:
        if self._pool is not None:
            return
        # Late import so the SQLite default doesn't require asyncpg.
        import asyncpg  # type: ignore[import-untyped]

        self._pool = await asyncpg.create_pool(
            self.dsn, min_size=self.pool_min, max_size=self.pool_max
        )
        async with self._pool.acquire() as conn:
            await conn.execute(_SCHEMA)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def record_transition(
        self, from_state: str, to_state: str, reason: str | None
    ) -> None:
        await self.init()
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO transitions(t, from_state, to_state, reason) VALUES ($1, $2, $3, $4)",
                datetime.now(UTC),
                from_state,
                to_state,
                reason,
            )

    async def record_ai_command(
        self,
        text: str,
        plan: dict[str, Any],
        explanation: str,
        repaired: bool = False,
    ) -> None:
        await self.init()
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO ai_commands(t, input, plan, explanation, repaired)"
                " VALUES ($1, $2, $3::jsonb, $4, $5)",
                datetime.now(UTC),
                text,
                json.dumps(plan, ensure_ascii=False),
                explanation,
                repaired,
            )

    async def list_transitions(self, limit: int = 100) -> list[dict[str, Any]]:
        await self.init()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, t, from_state, to_state, reason FROM transitions"
                " ORDER BY id DESC LIMIT $1",
                limit,
            )
        return [
            {
                "id": r["id"],
                "t": r["t"].isoformat(),
                "from_state": r["from_state"],
                "to_state": r["to_state"],
                "reason": r["reason"],
            }
            for r in rows
        ]

    async def list_ai_commands(self, limit: int = 100) -> list[dict[str, Any]]:
        await self.init()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, t, input, plan, explanation, repaired FROM ai_commands"
                " ORDER BY id DESC LIMIT $1",
                limit,
            )
        return [
            {
                "id": r["id"],
                "t": r["t"].isoformat(),
                "input": r["input"],
                # asyncpg returns JSONB as a Python object already; defensive
                # fallback in case the driver returns it as a string.
                "plan": r["plan"] if isinstance(r["plan"], dict) else json.loads(r["plan"]),
                "explanation": r["explanation"],
                "repaired": r["repaired"],
            }
            for r in rows
        ]

    async def counts(self) -> dict[str, int]:
        await self.init()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT (SELECT COUNT(*) FROM transitions) AS t,"
                " (SELECT COUNT(*) FROM ai_commands) AS a"
            )
        return {"transitions": row["t"], "ai_commands": row["a"]}

    async def prune(
        self, keep_transitions: int, keep_ai_commands: int
    ) -> dict[str, int]:
        await self.init()
        deleted = {"transitions": 0, "ai_commands": 0}
        async with self._pool.acquire() as conn:
            for table, keep in (
                ("transitions", keep_transitions),
                ("ai_commands", keep_ai_commands),
            ):
                result = await conn.execute(
                    f"DELETE FROM {table} WHERE id NOT IN"
                    f" (SELECT id FROM {table} ORDER BY id DESC LIMIT $1)",
                    keep,
                )
                # asyncpg returns "DELETE <n>".
                try:
                    deleted[table] = int(result.split()[-1])
                except (IndexError, ValueError):
                    deleted[table] = 0
        return deleted
