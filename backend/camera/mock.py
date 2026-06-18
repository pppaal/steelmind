"""Software-only Camera: renders a synthetic scene as an uncompressed BMP.

BMP is chosen so the simulator has zero image-codec dependencies (no Pillow /
OpenCV) yet still serves a real, browser-renderable, *live* frame — a marker
drifts across a faint grid so the operator can see the feed is updating. Real
drivers (OpenCV/USB) return JPEG through the same interface."""

from __future__ import annotations

import math
import struct
import time

from .base import Camera, CameraError


def _encode_bmp(width: int, height: int, pixels: bytes) -> bytes:
    """Wrap a bottom-up BGR pixel buffer in a 24-bit BMP header."""
    row_bytes = width * 3
    file_size = 54 + len(pixels)
    header = struct.pack("<2sIHHI", b"BM", file_size, 0, 0, 54)
    dib = struct.pack(
        "<IiiHHIIiiII", 40, width, height, 1, 24, 0, row_bytes * height, 2835, 2835, 0, 0
    )
    return header + dib + pixels


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
        return self._render(), "image/bmp"

    def _render(self) -> bytes:
        w, h = self._w, self._h
        row_bytes = w * 3  # 24-bit; widths chosen so this stays 4-byte aligned
        t = time.monotonic()
        # Marker drifts on a Lissajous path so successive frames differ.
        cx = int((0.5 + 0.4 * math.sin(t)) * w)
        cy = int((0.5 + 0.4 * math.cos(t * 0.7)) * h)
        r = max(4, w // 16)
        r2 = r * r
        buf = bytearray(row_bytes * h)
        for fy in range(h):  # file rows are bottom-up
            y = h - 1 - fy
            base = fy * row_bytes
            for x in range(w):
                if (x - cx) * (x - cx) + (y - cy) * (y - cy) <= r2:
                    b, g, red = 90, 180, 80  # green marker
                elif x % 20 == 0 or y % 20 == 0:
                    b, g, red = 46, 40, 40  # faint grid
                else:
                    b, g, red = 22, 18, 18  # background
                i = base + x * 3
                buf[i] = b
                buf[i + 1] = g
                buf[i + 2] = red
        return _encode_bmp(w, h, bytes(buf))
