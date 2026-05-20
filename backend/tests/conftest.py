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
_KF_FD, _KF_PATH = tempfile.mkstemp(prefix="steelmind-kf-", suffix=".json")
os.close(_KF_FD)
os.unlink(_KF_PATH)
os.environ.setdefault("KEYFRAMES_FILE", _KF_PATH)
_RT_FD, _RT_PATH = tempfile.mkstemp(prefix="steelmind-rt-", suffix=".json")
os.close(_RT_FD)
os.unlink(_RT_PATH)
os.environ.setdefault("ROUTINES_FILE", _RT_PATH)


@pytest.fixture()
def fresh_app(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Return a TestClient against a freshly-imported backend.main, with
    per-test temp files for every persisted store and a clean state
    machine. Tests that previously shared the module-level `ctx` (and so
    leaked state across the suite) should use this, not `client`."""
    fd, path = tempfile.mkstemp(prefix="steelmind-fresh-", suffix=".db")
    os.close(fd)
    monkeypatch.setenv("JOURNAL_DB", path)
    temp_paths = [path]
    for var, prefix in (
        ("CALIBRATION_FILE", "steelmind-fresh-cal-"),
        ("KEYFRAMES_FILE", "steelmind-fresh-kf-"),
        ("ROUTINES_FILE", "steelmind-fresh-rt-"),
    ):
        f, p = tempfile.mkstemp(prefix=prefix, suffix=".json")
        os.close(f)
        os.unlink(p)
        monkeypatch.setenv(var, p)
        temp_paths.append(p)
    # Drop the cached module so import-time globals (ctx, configure_logging
    # handlers) rebind against the new env.
    for name in list(sys.modules):
        if name == "backend.main" or name.startswith("backend.main."):
            del sys.modules[name]
    main = importlib.import_module("backend.main")
    with TestClient(main.app) as client:
        yield client
    for p in temp_paths:
        try:
            os.unlink(p)
        except OSError:
            pass
