from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS transitions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    t           TEXT    NOT NULL,
    from_state  TEXT    NOT NULL,
    to_state    TEXT    NOT NULL,
    reason      TEXT
);

CREATE TABLE IF NOT EXISTS ai_commands (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    t           TEXT    NOT NULL,
    input       TEXT    NOT NULL,
    plan_json   TEXT    NOT NULL,
    explanation TEXT    NOT NULL,
    repaired    INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_transitions_t ON transitions(t);
CREATE INDEX IF NOT EXISTS idx_ai_commands_t ON ai_commands(t);
"""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Journal:
    """SQLite-backed event log. All sqlite3 calls run on a thread via
    asyncio.to_thread so the event loop is never blocked by disk I/O."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._lock = asyncio.Lock()
        self._conn: sqlite3.Connection | None = None

    async def init(self) -> None:
        if self._conn is not None:
            return
        async with self._lock:
            if self._conn is not None:
                return
            self._conn = await asyncio.to_thread(self._open_sync)

    def _open_sync(self) -> sqlite3.Connection:
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False because asyncio.to_thread may run subsequent
        # operations on different worker threads; we serialize via self._lock.
        conn = sqlite3.connect(self.path, check_same_thread=False)
        # WAL lets readers (journal queries) run concurrently with writers
        # (broadcaster + ai_command append) without blocking. busy_timeout
        # makes any rare write contention wait briefly instead of erroring.
        # NORMAL synchronous is the WAL-recommended balance: safe across
        # process crashes, slightly relaxed vs FULL on power-loss durability.
        if self.path != ":memory:":
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.executescript(SCHEMA)
        conn.commit()
        return conn

    async def close(self) -> None:
        async with self._lock:
            if self._conn is not None:
                await asyncio.to_thread(self._conn.close)
                self._conn = None

    async def record_transition(
        self, from_state: str, to_state: str, reason: str | None
    ) -> None:
        await self._exec(
            "INSERT INTO transitions(t, from_state, to_state, reason) VALUES (?, ?, ?, ?)",
            (_now_iso(), from_state, to_state, reason),
        )

    async def record_ai_command(
        self,
        text: str,
        plan: dict[str, Any],
        explanation: str,
        repaired: bool = False,
    ) -> None:
        await self._exec(
            "INSERT INTO ai_commands(t, input, plan_json, explanation, repaired) VALUES (?, ?, ?, ?, ?)",
            (_now_iso(), text, json.dumps(plan, ensure_ascii=False), explanation, 1 if repaired else 0),
        )

    async def list_transitions(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = await self._query(
            "SELECT id, t, from_state, to_state, reason FROM transitions ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [
            {"id": r[0], "t": r[1], "from_state": r[2], "to_state": r[3], "reason": r[4]}
            for r in rows
        ]

    async def list_ai_commands(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = await self._query(
            "SELECT id, t, input, plan_json, explanation, repaired FROM ai_commands ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [
            {
                "id": r[0],
                "t": r[1],
                "input": r[2],
                "plan": json.loads(r[3]),
                "explanation": r[4],
                "repaired": bool(r[5]),
            }
            for r in rows
        ]

    async def counts(self) -> dict[str, int]:
        rows = await self._query(
            "SELECT (SELECT COUNT(*) FROM transitions), (SELECT COUNT(*) FROM ai_commands)",
            (),
        )
        n_t, n_ai = rows[0]
        return {"transitions": n_t, "ai_commands": n_ai}

    async def prune(self, keep_transitions: int, keep_ai_commands: int) -> dict[str, int]:
        """Keep only the most recent N rows per table. Returns rows deleted.

        Cheap, idempotent, safe to call from a periodic background task; the
        SQLite write lock is serialized via self._lock so it can't interleave
        with appends from broadcasters."""
        deleted = {"transitions": 0, "ai_commands": 0}
        for table, keep in (
            ("transitions", keep_transitions),
            ("ai_commands", keep_ai_commands),
        ):
            res = await self._exec_returning(
                f"DELETE FROM {table} WHERE id NOT IN "
                f"(SELECT id FROM {table} ORDER BY id DESC LIMIT ?)",
                (keep,),
            )
            deleted[table] = res
        return deleted

    async def _exec_returning(self, sql: str, params: tuple) -> int:
        await self.init()
        async with self._lock:
            assert self._conn is not None
            return await asyncio.to_thread(self._exec_returning_sync, self._conn, sql, params)

    @staticmethod
    def _exec_returning_sync(conn: sqlite3.Connection, sql: str, params: tuple) -> int:
        cur = conn.execute(sql, params)
        n = cur.rowcount
        conn.commit()
        return n

    async def _exec(self, sql: str, params: tuple) -> None:
        await self.init()
        async with self._lock:
            assert self._conn is not None
            await asyncio.to_thread(self._exec_sync, self._conn, sql, params)

    @staticmethod
    def _exec_sync(conn: sqlite3.Connection, sql: str, params: tuple) -> None:
        conn.execute(sql, params)
        conn.commit()

    async def _query(self, sql: str, params: tuple) -> list[tuple]:
        await self.init()
        async with self._lock:
            assert self._conn is not None
            return await asyncio.to_thread(self._query_sync, self._conn, sql, params)

    @staticmethod
    def _query_sync(conn: sqlite3.Connection, sql: str, params: tuple) -> list[tuple]:
        return list(conn.execute(sql, params).fetchall())
