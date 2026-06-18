"""Software-only Camera: renders a synthetic scene with no image-codec deps.

A marker drifts across a faint grid so the operator can see the feed is live.
Snapshots are served as BMP (browser-friendly, dependency-free); the vision
frame is PNG, which Claude's vision API accepts (it rejects BMP). Real drivers
(OpenCV/USB) return JPEG through the same interface."""

from __future__ import annotations

import math
import time

from .base import Camera, CameraError
from .encode import encode_bmp, encode_png


class MockCamera(Camera):
    def __init__(self, width: int = 160, height: int = 120) -> None:
        self._w = width
        self._h = height
        self._open = False

    @property
    def available(self) -> bool:
        return self._open

    @property
    def width(self) -> int:
        return self._w

    @property
    def height(self) -> int:
        return self._h

    async def init(self) -> None:
        self._open = True

    async def close(self) -> None:
        self._open = False

    async def read_frame(self) -> tuple[bytes, str]:
        if not self._open:
            raise CameraError("camera not open")
        w, h, rgb = self._pixels()
        return encode_bmp(w, h, rgb), "image/bmp"

    async def read_vision_frame(self) -> tuple[str, bytes]:
        if not self._open:
            raise CameraError("camera not open")
        w, h, rgb = self._pixels()
        return "image/png", encode_png(w, h, rgb)

    def _pixels(self) -> tuple[int, int, bytes]:
        """Render the scene to a top-to-bottom RGB buffer."""
        w, h = self._w, self._h
        t = time.monotonic()
        # Marker drifts on a Lissajous path so successive frames differ.
        cx = int((0.5 + 0.4 * math.sin(t)) * w)
        cy = int((0.5 + 0.4 * math.cos(t * 0.7)) * h)
        r = max(4, w // 16)
        r2 = r * r
        buf = bytearray(w * h * 3)
        for y in range(h):
            base = y * w * 3
            for x in range(w):
                if (x - cx) * (x - cx) + (y - cy) * (y - cy) <= r2:
                    rgb = (80, 180, 90)  # green marker
                elif x % 20 == 0 or y % 20 == 0:
                    rgb = (40, 40, 46)  # faint grid
                else:
                    rgb = (18, 18, 22)  # background
                i = base + x * 3
                buf[i], buf[i + 1], buf[i + 2] = rgb
        return w, h, bytes(buf)
