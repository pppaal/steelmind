"""Camera abstraction: mock BMP rendering, the build_camera factory, and the
/camera/info + /camera/snapshot endpoints."""

import struct

import pytest
from fastapi.testclient import TestClient

from backend.camera import MockCamera, build_camera
from backend.camera.base import Camera, CameraError
from backend.camera.encode import encode_png


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


def test_encode_png_is_valid() -> None:
    png = encode_png(2, 2, bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255]))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"  # PNG signature
    assert png[12:16] == b"IHDR"
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (2, 2)
    assert png[-8:-4] == b"IEND"


@pytest.mark.asyncio
async def test_mock_vision_frame_is_png() -> None:
    cam = MockCamera(width=160, height=120)
    await cam.init()
    media_type, data = await cam.read_vision_frame()
    assert media_type == "image/png"
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.asyncio
async def test_base_vision_frame_passthrough_and_reject() -> None:
    class JpegCam(Camera):
        available = True
        width = 4
        height = 4

        async def init(self) -> None: ...
        async def close(self) -> None: ...

        async def read_frame(self) -> tuple[bytes, str]:
            return b"\xff\xd8jpeg", "image/jpeg"

    media_type, _data = await JpegCam().read_vision_frame()
    assert media_type == "image/jpeg"  # already supported → passthrough

    class BmpCam(JpegCam):
        async def read_frame(self) -> tuple[bytes, str]:
            return b"BMxx", "image/bmp"

    with pytest.raises(CameraError):
        await BmpCam().read_vision_frame()  # bmp isn't vision-compatible


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


def test_build_camera_opencv_constructs_without_cv2(monkeypatch) -> None:
    # Construction must not import cv2 (lazy at init), so the factory works
    # even where opencv isn't installed.
    from backend.camera.opencv import OpenCVCamera

    monkeypatch.setenv("CAMERA", "opencv")
    monkeypatch.setenv("CAMERA_DEVICE", "2")
    cam = build_camera()
    assert isinstance(cam, OpenCVCamera)
    assert cam.available is False  # not opened yet
    assert cam._device == 2


@pytest.mark.asyncio
async def test_opencv_read_before_init_raises() -> None:
    from backend.camera.opencv import OpenCVCamera

    with pytest.raises(CameraError):
        await OpenCVCamera().read_frame()


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
    assert fresh_app.get("/camera/stream").status_code == 503


def test_multipart_chunk_framing() -> None:
    from backend.main.routes_camera import _multipart_chunk

    chunk = _multipart_chunk(b"\x01\x02\x03", "image/jpeg")
    assert chunk.startswith(b"--frame\r\n")
    assert b"Content-Type: image/jpeg" in chunk
    assert b"Content-Length: 3" in chunk
    assert chunk.endswith(b"\x01\x02\x03\r\n")


@pytest.mark.asyncio
async def test_camera_stream_generator_yields_a_frame(camera_app: TestClient) -> None:
    # Drive the StreamingResponse generator directly for one frame, then close
    # it — consuming the endless stream over HTTP would hang the test client.
    from backend.main.routes_camera import camera_stream

    resp = await camera_stream()
    assert "multipart/x-mixed-replace" in resp.media_type
    agen = resp.body_iterator
    chunk = await agen.__anext__()
    await agen.aclose()
    assert b"--frame" in chunk
    assert b"image/bmp" in chunk
