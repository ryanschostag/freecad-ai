import mimetypes
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.storage import get_object_bytes, presign_get

router = APIRouter()


@router.get("/artifacts/{artifact_id}")
def get_artifact(artifact_id: str, db: Session = Depends(get_db)):
    art = db.query(models.DimArtifact).filter(models.DimArtifact.artifact_id == artifact_id).one_or_none()
    if not art:
        raise HTTPException(404, "artifact not found")
    url, exp = presign_get(art.object_key, 900)
    return {
        "artifact_id": str(uuid.UUID(art.artifact_id)),
        "kind": art.kind,
        "object_key": art.object_key,
        "download_url": url,
        "proxy_download_url": f"/v1/artifacts/{art.artifact_id}/content",
        "expires_at": exp.isoformat(),
    }


@router.get("/artifacts/{artifact_id}/content")
def get_artifact_content(artifact_id: str, db: Session = Depends(get_db)):
    art = db.query(models.DimArtifact).filter(models.DimArtifact.artifact_id == artifact_id).one_or_none()
    if not art:
        raise HTTPException(404, "artifact not found")

    try:
        data = get_object_bytes(art.object_key)
    except Exception as exc:
        raise HTTPException(502, f"failed to fetch artifact content: {exc}") from exc

    content_type = mimetypes.guess_type(art.object_key)[0] or "application/octet-stream"
    headers = {
        "Content-Disposition": f'attachment; filename="{art.object_key.split("/")[-1]}"',
        "X-Artifact-Id": art.artifact_id,
        "X-Artifact-Kind": art.kind,
    }
    return StreamingResponse(iter([data]), media_type=content_type, headers=headers)


@router.get("/sessions/{session_id}/artifacts")
def list_session_artifacts(session_id: str, db: Session = Depends(get_db)):
    s = db.query(models.DimSession).filter(models.DimSession.session_id == session_id).one_or_none()
    if not s:
        raise HTTPException(404, "session not found")

    rows = (
        db.query(models.DimArtifact, models.FactArtifactEvent)
        .join(models.FactArtifactEvent, models.FactArtifactEvent.artifact_id == models.DimArtifact.artifact_id)
        .filter(models.FactArtifactEvent.session_id == session_id)
        .order_by(models.DimArtifact.created_at.asc())
        .all()
    )
    out = []
    for a, ev in rows:
        out.append(
            {
                "artifact_id": str(uuid.UUID(a.artifact_id)),
                "kind": a.kind,
                "object_key": a.object_key,
                "created_at": a.created_at.isoformat(),
                "sha256": a.sha256,
                "bytes": a.bytes,
                "message_id": ev.message_id,
                "event_type": ev.event_type,
            }
        )
    return {"artifacts": out}
