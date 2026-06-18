"""Camera abstraction layer — the visual analogue of the HAL.

A Camera yields encoded image frames (JPEG from real drivers, BMP from the
dependency-free mock). Higher layers (the snapshot endpoint, and later the
vision-grounded AI commander) consume frames through this interface, so the
same code runs against the mock simulator and a real USB/CSI camera."""

from __future__ import annotations

from abc import ABC, abstractmethod


class CameraError(Exception):
    """Driver-level camera failure."""


class Camera(ABC):
    """Contract every camera implementation honors. read_frame returns the
    latest frame as (encoded_bytes, mime_type) so the endpoint can serve it
    verbatim regardless of codec."""

    @property
    @abstractmethod
    def available(self) -> bool:
        """True once init() has opened the device and it can serve frames."""

    @property
    @abstractmethod
    def width(self) -> int: ...

    @property
    @abstractmethod
    def height(self) -> int: ...

    @abstractmethod
    async def init(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def read_frame(self) -> tuple[bytes, str]:
        """Return (data, mime_type) for the most recent frame."""

    async def read_vision_frame(self) -> tuple[str, bytes]:
        """Return (media_type, data) in a format Claude vision accepts.

        Default: pass the frame through when it's already a supported codec
        (real drivers return JPEG). Implementations whose snapshot codec isn't
        vision-compatible (e.g. the mock's BMP) override this."""
        from .encode import VISION_MEDIA_TYPES

        data, mime = await self.read_frame()
        if mime in VISION_MEDIA_TYPES:
            return mime, data
        raise CameraError(f"frame codec {mime} is not vision-compatible")
