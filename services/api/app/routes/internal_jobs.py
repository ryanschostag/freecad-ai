from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from sqlalchemy.orm import Session

from app.db import get_db
from app.models import JobRun


router = APIRouter()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class JobStartedIn(BaseModel):
    worker_id: Optional[str] = None


class JobCompleteIn(BaseModel):
    status: str  # "finished" | "failed"
    result: Optional[dict[str, Any]] = None
    error: Optional[dict[str, Any]] = None


@router.post("/jobs/{job_id}/started")
def mark_job_started(job_id: str, payload: JobStartedIn, db: Session = Depends(get_db)):
    """Worker callback: move a job to started.

    Enforces the transition: queued -> started.
    """
    jr = db.get(JobRun, job_id)
    if not jr:
        raise HTTPException(status_code=404, detail="job not found")

    if jr.status in ("finished", "failed"):
        return {"ok": True, "status": jr.status}

    # Allow idempotent updates.
    if jr.status not in ("queued", "started"):
        raise HTTPException(status_code=409, detail=f"invalid state transition: {jr.status} -> started")

    jr.status = "started"
    jr.started_at = jr.started_at or _utc_now()
    if payload.worker_id:
        jr.worker_id = payload.worker_id

    db.add(jr)
    db.commit()
    return {"ok": True, "status": jr.status}


@router.post("/jobs/{job_id}/complete")
def mark_job_complete(job_id: str, payload: JobCompleteIn, db: Session = Depends(get_db)):
    """Worker callback: persist result/error so Redis TTLs don't matter."""
    if payload.status not in ("finished", "failed"):
        raise HTTPException(status_code=400, detail="status must be 'finished' or 'failed'")

    jr = db.get(JobRun, job_id)
    if not jr:
        raise HTTPException(status_code=404, detail="job not found")

    # Allow idempotent completion.
    if jr.status in ("finished", "failed"):
        return {"ok": True, "status": jr.status}

    if jr.status not in ("queued", "started", "retrying"):
        raise HTTPException(status_code=409, detail=f"invalid state transition: {jr.status} -> {payload.status}")

    if jr.status == "queued":
        jr.started_at = jr.started_at or _utc_now()

    jr.status = payload.status
    jr.finished_at = _utc_now()
    jr.result_json = payload.result
    jr.error_json = payload.error

    db.add(jr)
    db.commit()
    return {"ok": True, "status": jr.status}


class JobRetryingIn(BaseModel):
    retry_count: int
    reason: Optional[str] = None


@router.post("/jobs/{job_id}/retrying")
def mark_job_retrying(job_id: str, payload: JobRetryingIn, db: Session = Depends(get_db)):
    """Worker callback: mark a job as retrying and emit a log event."""
    jr = db.get(JobRun, job_id)
    if not jr:
        raise HTTPException(status_code=404, detail="job not found")

    if jr.status in ("finished", "failed"):
        return {"ok": True, "status": jr.status}

    jr.status = "retrying"
    jr.started_at = jr.started_at or _utc_now()
    db.add(jr)
    if jr.session_id:
        from app.models import LogEvent
        db.add(LogEvent(session_id=jr.session_id, type="job.retrying", payload_json={"job_id": job_id, "retry-count": payload.retry_count, "reason": payload.reason}))
    db.commit()
    return {"ok": True, "status": jr.status}
