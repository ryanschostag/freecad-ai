import os
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.db import get_db
from app import models

router = APIRouter()

@router.get("/artifacts/{artifact_id}")
def get_artifact(artifact_id: str, db: Session = Depends(get_db)):
    art = db.query(models.DimArtifact).filter(models.DimArtifact.artifact_id==artifact_id).one_or_none()
    if not art:
        raise HTTPException(404, "artifact not found")
    # localfs stream
    path = art.object_key
    if not os.path.exists(path):
        raise HTTPException(404, "artifact missing on disk")
    return FileResponse(path, filename=os.path.basename(path))
