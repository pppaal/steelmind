import importlib
import os
import sys
import tempfile

import pytest
from fastapi.testclient import TestClient

# Point persistence at per-process temp files before backend.main is
# imported. Each pytest invocation gets its own DB + calibration so runs
# don't collide and the repo working dir stays clean.
_JOURNAL_FD, _JOURNAL_PATH = tempfile.mkstemp(prefix="steelmind-test-", suffix=".db")
os.close(_JOURNAL_FD)
os.environ.setdefault("JOURNAL_DB", _JOURNAL_PATH)
_CAL_FD, _CAL_PATH = tempfile.mkstemp(prefix="steelmind-cal-", suffix=".json")
os.close(_CAL_FD)
os.unlink(_CAL_PATH)  # absent file → empty calibration, which is what we want
os.environ.setdefault("CALIBRATION_FILE", _CAL_PATH)


@pytest.fixture()
def fresh_app(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Return a TestClient against a freshly-imported backend.main, with a
    per-test JOURNAL_DB + CALIBRATION_FILE and a clean state machine. Tests
    that previously shared the module-level `ctx` (and so leaked state
    across the suite) should depend on this fixture instead of `client`."""
    fd, path = tempfile.mkstemp(prefix="steelmind-fresh-", suffix=".db")
    os.close(fd)
    monkeypatch.setenv("JOURNAL_DB", path)
    cfd, cpath = tempfile.mkstemp(prefix="steelmind-fresh-cal-", suffix=".json")
    os.close(cfd)
    os.unlink(cpath)
    monkeypatch.setenv("CALIBRATION_FILE", cpath)
    # Drop the cached module so import-time globals (ctx, configure_logging
    # handlers) rebind against the new env.
    for name in list(sys.modules):
        if name == "backend.main" or name.startswith("backend.main."):
            del sys.modules[name]
    main = importlib.import_module("backend.main")
    with TestClient(main.app) as client:
        yield client
    for p in (path, cpath):
        try:
            os.unlink(p)
        except OSError:
            pass
