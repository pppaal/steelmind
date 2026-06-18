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
