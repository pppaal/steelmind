"""OpenCV camera driver. Activated by CAMERA=opencv.

Wraps cv2.VideoCapture and encodes frames as JPEG (which both the snapshot
endpoint and Claude vision accept). cv2 is imported lazily at init() so the
dependency stays optional — the mock and the rest of the stack don't need it.
Install: pip install opencv-python-headless"""

from __future__ import annotations

import asyncio
from typing import Any

from .base import Camera, CameraError


class OpenCVCamera(Camera):
    def __init__(
        self,
        device: int | str = 0,
        width: int = 640,
        height: int = 480,
        jpeg_quality: int = 80,
    ) -> None:
        self._device = device
        self._w = width
        self._h = height
        self._quality = jpeg_quality
        self._cap: Any = None
        self._cv2: Any = None

    @property
    def available(self) -> bool:
        return self._cap is not None

    @property
    def width(self) -> int:
        return self._w

    @property
    def height(self) -> int:
        return self._h

    async def init(self) -> None:
        try:
            import cv2  # lazy: keeps opencv optional
        except ImportError as e:
            raise CameraError("CAMERA=opencv requires opencv-python(-headless)") from e
        self._cv2 = cv2
        cap = cv2.VideoCapture(self._device)
        if not cap.isOpened():
            raise CameraError(f"could not open camera device {self._device!r}")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._h)
        # Reflect what the device actually gave us.
        self._w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or self._w
        self._h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or self._h
        self._cap = cap

    async def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    async def read_frame(self) -> tuple[bytes, str]:
        if self._cap is None:
            raise CameraError("camera not open")
        # cap.read() is blocking — keep it off the event loop.
        ok, frame = await asyncio.to_thread(self._cap.read)
        if not ok or frame is None:
            raise CameraError("frame read failed")
        ok, buf = self._cv2.imencode(
            ".jpg", frame, [self._cv2.IMWRITE_JPEG_QUALITY, self._quality]
        )
        if not ok:
            raise CameraError("JPEG encode failed")
        return bytes(buf), "image/jpeg"
