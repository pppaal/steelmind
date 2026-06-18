"""Camera abstraction: mock BMP rendering, the build_camera factory, and the
/camera/info + /camera/snapshot endpoints."""

import importlib
import os
import struct
import sys
import tempfile

import pytest
from fastapi.testclient import TestClient

from backend.camera import MockCamera, build_camera
from backend.camera.base import CameraError


@pytest.mark.asyncio
async def test_mock_camera_renders_valid_bmp() -> None:
    cam = MockCamera(width=160, height=120)
    await cam.init()
    assert cam.available is True
    data, mime = await cam.read_frame()
    assert mime == "image/bmp"
    assert data[:2] == b"BM"  # BMP magic
    # Header declares the right dimensions and total size.
    file_size = struct.unpack("<I", data[2:6])[0]
    width, height = struct.unpack("<ii", data[18:26])
    assert (width, height) == (160, 120)
    assert file_size == len(data) == 54 + 160 * 120 * 3


@pytest.mark.asyncio
async def test_mock_camera_closed_raises() -> None:
    cam = MockCamera()
    with pytest.raises(CameraError):
        await cam.read_frame()


def test_build_camera_default_is_none(monkeypatch) -> None:
    monkeypatch.delenv("CAMERA", raising=False)
    assert build_camera() is None


def test_build_camera_mock(monkeypatch) -> None:
    monkeypatch.setenv("CAMERA", "mock")
    cam = build_camera()
    assert isinstance(cam, MockCamera)


def test_build_camera_unknown_rejected(monkeypatch) -> None:
    monkeypatch.setenv("CAMERA", "hal9000")
    with pytest.raises(RuntimeError, match="unknown CAMERA"):
        build_camera()


@pytest.fixture()
def camera_app(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Boot the app with the mock camera enabled."""
    fd, db = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setenv("JOURNAL_DB", db)
    for var in ("CALIBRATION_FILE", "KEYFRAMES_FILE", "ROUTINES_FILE"):
        f, p = tempfile.mkstemp(suffix=".json")
        os.close(f)
        os.unlink(p)
        monkeypatch.setenv(var, p)
    monkeypatch.setenv("CAMERA", "mock")
    for name in list(sys.modules):
        if name == "backend.main" or name.startswith("backend.main."):
            del sys.modules[name]
    main = importlib.import_module("backend.main")
    with TestClient(main.app) as client:
        yield client
    try:
        os.unlink(db)
    except OSError:
        pass


def test_camera_info_and_snapshot(camera_app: TestClient) -> None:
    info = camera_app.get("/camera/info").json()
    assert info == {"available": True, "width": 160, "height": 120}
    r = camera_app.get("/camera/snapshot")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/bmp"
    assert r.content[:2] == b"BM"


def test_camera_absent_by_default(fresh_app: TestClient) -> None:
    # fresh_app ships no CAMERA → info reports unavailable, snapshot 503.
    assert fresh_app.get("/camera/info").json() == {"available": False}
    assert fresh_app.get("/camera/snapshot").status_code == 503
