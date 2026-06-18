"""Factory for the optional camera backend, mirroring build_hardware()."""

from __future__ import annotations

import logging
import os

from .base import Camera, CameraError
from .mock import MockCamera

logger = logging.getLogger("steelmind.camera")

__all__ = ["Camera", "CameraError", "MockCamera", "build_camera"]


def build_camera() -> Camera | None:
    """Resolve CAMERA env to a camera, or None when disabled (the default, so
    the demo and tests have no feed unless asked). Real drivers are late-
    imported so their deps (opencv-python) stay optional."""
    backend = os.getenv("CAMERA", "none").lower()
    if backend in ("none", "", "off"):
        return None
    if backend == "mock":
        w = int(os.getenv("CAMERA_WIDTH", "160"))
        h = int(os.getenv("CAMERA_HEIGHT", "120"))
        logger.info("camera: mock %dx%d", w, h)
        return MockCamera(width=w, height=h)
    raise RuntimeError(f"unknown CAMERA: {backend!r}")
