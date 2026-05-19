import importlib
import os
import sys
import tempfile

import pytest
from fastapi.testclient import TestClient

# Point the journal at a per-process temp file before backend.main is imported.
# Each pytest invocation gets its own DB so concurrent runs don't collide.
_JOURNAL_FD, _JOURNAL_PATH = tempfile.mkstemp(prefix="steelmind-test-", suffix=".db")
os.close(_JOURNAL_FD)
os.environ.setdefault("JOURNAL_DB", _JOURNAL_PATH)


@pytest.fixture()
def fresh_app(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Return a TestClient against a freshly-imported backend.main, with a
    per-test JOURNAL_DB and a clean state machine. Tests that previously
    shared the module-level `ctx` (and so leaked state across the suite)
    should depend on this fixture instead of the legacy `client`."""
    fd, path = tempfile.mkstemp(prefix="steelmind-fresh-", suffix=".db")
    os.close(fd)
    monkeypatch.setenv("JOURNAL_DB", path)
    # Drop the cached module so import-time globals (ctx, configure_logging
    # handlers) rebind against the new env.
    for name in list(sys.modules):
        if name == "backend.main" or name.startswith("backend.main."):
            del sys.modules[name]
    main = importlib.import_module("backend.main")
    with TestClient(main.app) as client:
        yield client
    try:
        os.unlink(path)
    except OSError:
        pass
