import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db import get_db
from app import models
from app.storage import presign_get

router = APIRouter()

@router.get("/artifacts/{artifact_id}")
def get_artifact(artifact_id: str, db: Session = Depends(get_db)):
    art = db.query(models.DimArtifact).filter(models.DimArtifact.artifact_id==artifact_id).one_or_none()
    if not art: raise HTTPException(404, "artifact not found")
    url, exp = presign_get(art.object_key, 900)
    return {"artifact_id": str(uuid.UUID(art.artifact_id)), "kind": art.kind, "object_key": art.object_key,
            "download_url": url, "expires_at": exp.isoformat()}
