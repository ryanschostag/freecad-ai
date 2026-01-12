from __future__ import annotations
import uuid
from fastapi import APIRouter, Depends, HTTPException
from redis import Redis
from rq.job import Job
from sqlalchemy.orm import Session
from app.db import get_db
from app.settings import settings
from app import models
from app.utils import upsert_time, sha256_bytes
from app.storage import presign_get

router = APIRouter()

def _redis():
    return Redis.from_url(settings.redis_url)

@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    try:
        j = Job.fetch(job_id, connection=_redis())
    except Exception:
        raise HTTPException(404, "job not found")

    status = j.get_status()  # queued/started/finished/failed/deferred
    mapped = status
    if status == "deferred":
        mapped = "queued"
    if mapped not in {"queued","started","finished","failed"}:
        mapped = "queued"

    # Pull session_id from meta if available
    session_id = (j.meta or {}).get("session_id")
    user_message_id = (j.meta or {}).get("user_message_id")

    resp = {
        "job_id": str(uuid.UUID(job_id)),
        "status": mapped,
        "session_id": session_id,
        "user_message_id": user_message_id,
        "result": None,
        "error": None,
    }

    if mapped == "finished":
        result = j.result or {}
        resp["result"] = result

        # Persist artifacts into DB once (idempotent on object_key + kind)
        now = result.get("ts")
        time_id = upsert_time(db, __import__("datetime").datetime.now(__import__("datetime").timezone.utc))
        arts = result.get("artifacts") or []
        for a in arts:
            kind = a.get("kind")
            object_key = a.get("object_key")
            if not kind or not object_key:
                continue
            exists = db.query(models.DimArtifact).filter(
                models.DimArtifact.kind == kind,
                models.DimArtifact.object_key == object_key
            ).one_or_none()
            if exists:
                continue
            art_id = str(uuid.uuid4())
            db.add(models.DimArtifact(
                artifact_id=art_id,
                kind=kind,
                storage_provider="minio",
                object_key=object_key,
                sha256=a.get("sha256"),
                bytes=a.get("bytes"),
            ))
            if session_id and user_message_id:
                db.add(models.FactArtifactEvent(
                    artifact_id=art_id, session_id=session_id, time_id=time_id,
                    message_id=user_message_id, event_type="created"
                ))
        db.commit()

    if mapped == "failed":
        resp["error"] = {"exc_info": str(j.exc_info)[:2000] if j.exc_info else "unknown error"}

    return resp
