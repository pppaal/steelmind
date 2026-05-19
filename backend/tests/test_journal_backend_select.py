import pytest

from backend.journal_base import JournalBase


def test_default_backend_is_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JOURNAL_BACKEND", raising=False)
    import importlib
    import sys

    for name in list(sys.modules):
        if name == "backend.main" or name.startswith("backend.main."):
            del sys.modules[name]
    main = importlib.import_module("backend.main")
    j = main._build_journal()
    assert isinstance(j, JournalBase)
    assert j.__class__.__name__ == "Journal"  # the SQLite impl


def test_postgres_backend_requires_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOURNAL_BACKEND", "postgres")
    monkeypatch.delenv("JOURNAL_DSN", raising=False)
    monkeypatch.delenv("JOURNAL_DSN_FILE", raising=False)
    import importlib
    import sys

    for name in list(sys.modules):
        if name == "backend.main" or name.startswith("backend.main."):
            del sys.modules[name]
    main = importlib.import_module("backend.main")
    with pytest.raises(RuntimeError, match="JOURNAL_DSN"):
        main._build_journal()


def test_unknown_backend_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOURNAL_BACKEND", "cassandra")
    import importlib
    import sys

    for name in list(sys.modules):
        if name == "backend.main" or name.startswith("backend.main."):
            del sys.modules[name]
    main = importlib.import_module("backend.main")
    with pytest.raises(RuntimeError, match="unknown JOURNAL_BACKEND"):
        main._build_journal()


def test_postgres_journal_class_is_importable() -> None:
    """asyncpg is optional; the module-level import shouldn't fail without it.
    A class instance can be created (no I/O); init() would lazy-import asyncpg."""
    from backend.journal_postgres import PostgresJournal

    j = PostgresJournal("postgresql://fake/fake")
    assert isinstance(j, JournalBase)
