"""Pure-Python image encoders (stdlib only).

The mock camera renders raw pixels; these turn them into wire formats without
pulling in Pillow/numpy. BMP is the browser-friendly snapshot format; PNG is
what Claude vision accepts (it rejects BMP), so a vision frame is encoded as
PNG via zlib."""

from __future__ import annotations

import struct
import zlib

# Image media types Claude's vision API accepts.
VISION_MEDIA_TYPES = ("image/jpeg", "image/png", "image/gif", "image/webp")


def encode_bmp(width: int, height: int, rgb_top_down: bytes) -> bytes:
    """24-bit BMP from a top-to-bottom RGB buffer (BMP stores rows bottom-up)."""
    row = width * 3
    out = bytearray(row * height)
    for y in range(height):
        src = y * row
        dst = (height - 1 - y) * row  # flip vertically
        for x in range(width):
            r = rgb_top_down[src + x * 3]
            g = rgb_top_down[src + x * 3 + 1]
            b = rgb_top_down[src + x * 3 + 2]
            i = dst + x * 3
            out[i] = b  # BMP is BGR
            out[i + 1] = g
            out[i + 2] = r
    header = struct.pack("<2sIHHI", b"BM", 54 + len(out), 0, 0, 54)
    dib = struct.pack(
        "<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(out), 2835, 2835, 0, 0
    )
    return header + dib + bytes(out)


def encode_png(width: int, height: int, rgb_top_down: bytes) -> bytes:
    """8-bit RGB PNG from a top-to-bottom RGB buffer."""

    def chunk(typ: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + typ
            + data
            + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
        )

    stride = width * 3
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0 (none) per scanline
        raw += rgb_top_down[y * stride : (y + 1) * stride]
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # color type 2 = RGB
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )
