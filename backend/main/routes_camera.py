"""Camera info + snapshot endpoints (the robot's eye)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse

from ..auth import require_viewer
from .context import ctx

router = APIRouter()

_BOUNDARY = "frame"
_STREAM_INTERVAL = 0.1  # ~10 fps cap for the MJPEG-style stream


def _multipart_chunk(data: bytes, mime: str) -> bytes:
    """One multipart/x-mixed-replace part for a single frame."""
    head = f"--{_BOUNDARY}\r\nContent-Type: {mime}\r\nContent-Length: {len(data)}\r\n\r\n"
    return head.encode("ascii") + data + b"\r\n"


@router.get("/camera/info", dependencies=[Depends(require_viewer)])
async def camera_info() -> dict:
    """Whether a camera is configured/open and its frame size, so the console
    only shows the panel when there's something to show."""
    cam = ctx.camera
    if cam is None or not cam.available:
        return {"available": False}
    return {"available": True, "width": cam.width, "height": cam.height}


@router.get("/camera/snapshot", dependencies=[Depends(require_viewer)])
async def camera_snapshot() -> Response:
    """Latest frame, served verbatim with the driver's mime type. 503 when no
    camera is configured."""
    cam = ctx.camera
    if cam is None or not cam.available:
        raise HTTPException(status_code=503, detail="no camera configured")
    data, mime = await cam.read_frame()
    return Response(content=data, media_type=mime, headers={"Cache-Control": "no-store"})


@router.get("/camera/stream", dependencies=[Depends(require_viewer)])
async def camera_stream() -> StreamingResponse:
    """Continuous MJPEG-style feed (multipart/x-mixed-replace). 503 when no
    camera is configured. Ends when the client disconnects."""
    cam = ctx.camera
    if cam is None or not cam.available:
        raise HTTPException(status_code=503, detail="no camera configured")

    async def frames() -> AsyncIterator[bytes]:
        while True:
            try:
                data, mime = await cam.read_frame()
            except Exception:
                break
            yield _multipart_chunk(data, mime)
            await asyncio.sleep(_STREAM_INTERVAL)

    return StreamingResponse(
        frames(),
        media_type=f"multipart/x-mixed-replace; boundary={_BOUNDARY}",
        headers={"Cache-Control": "no-store"},
    )
