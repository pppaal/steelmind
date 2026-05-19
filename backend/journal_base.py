"""Abstract Journal interface so the storage backend is swappable.

SQLite (default) covers the single-instance demo; Postgres is for fleets
where multiple backend replicas share a database.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class JournalBase(ABC):
    @abstractmethod
    async def init(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def record_transition(
        self, from_state: str, to_state: str, reason: str | None
    ) -> None: ...

    @abstractmethod
    async def record_ai_command(
        self,
        text: str,
        plan: dict[str, Any],
        explanation: str,
        repaired: bool = False,
    ) -> None: ...

    @abstractmethod
    async def list_transitions(self, limit: int = 100) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def list_ai_commands(self, limit: int = 100) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def counts(self) -> dict[str, int]: ...

    @abstractmethod
    async def prune(
        self, keep_transitions: int, keep_ai_commands: int
    ) -> dict[str, int]: ...
