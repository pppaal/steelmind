import contextlib
import importlib
import os
import sys
import tempfile
from collections.abc import Iterator

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


@contextlib.contextmanager
def boot_app(monkeypatch: pytest.MonkeyPatch, **env: str) -> Iterator[TestClient]:
    """Boot a TestClient against a freshly-imported backend.main with per-test
    temp files for every persisted store, plus any extra env overrides. The
    module cache is dropped first so import-time globals (ctx, config,
    logging handlers) rebind against the new env."""
    temp_paths: list[str] = []
    fd, db = tempfile.mkstemp(prefix="steelmind-test-", suffix=".db")
    os.close(fd)
    monkeypatch.setenv("JOURNAL_DB", db)
    temp_paths.append(db)
    for var in ("CALIBRATION_FILE", "KEYFRAMES_FILE", "ROUTINES_FILE"):
        f, p = tempfile.mkstemp(prefix="steelmind-test-", suffix=".json")
        os.close(f)
        os.unlink(p)
        monkeypatch.setenv(var, p)
        temp_paths.append(p)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    for name in list(sys.modules):
        if name == "backend.main" or name.startswith("backend.main."):
            del sys.modules[name]
    main = importlib.import_module("backend.main")
    try:
        with TestClient(main.app) as client:
            yield client
    finally:
        for p in temp_paths:
            with contextlib.suppress(OSError):
                os.unlink(p)


@pytest.fixture()
def fresh_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A TestClient against a fresh backend.main with the default sim config —
    isolated per-test state, no leakage through the module-level ctx."""
    with boot_app(monkeypatch) as client:
        yield client


@pytest.fixture()
def so100_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Boot the app against the SO-100 config, which has a planar chain."""
    with boot_app(monkeypatch, ROBOT_CONFIG="backend/configs/so100_arm.json") as client:
        yield client


@pytest.fixture()
def camera_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Boot the app with the mock camera enabled."""
    with boot_app(monkeypatch, CAMERA="mock") as client:
        yield client


@pytest.fixture()
def sim_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Boot the app on the physics simulation hardware backend."""
    with boot_app(monkeypatch, ROBOT_HARDWARE="sim") as client:
        yield client


@pytest.fixture()
def app_booter(monkeypatch: pytest.MonkeyPatch):
    """A factory for booting the app with arbitrary env overrides:
    `with app_booter(ROBOT_HARDWARE="sim", ROBOT_CONFIG=...) as client: ...`."""
    return lambda **env: boot_app(monkeypatch, **env)
