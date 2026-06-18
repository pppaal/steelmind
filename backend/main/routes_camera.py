"""Camera info + snapshot endpoints (the robot's eye)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from ..auth import require_viewer
from .context import ctx

router = APIRouter()


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
