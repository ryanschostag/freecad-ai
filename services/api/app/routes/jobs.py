from __future__ import annotations
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from redis import Redis
from rq.job import Job
from sqlalchemy.orm import Session
from app.db import get_db
from app.settings import settings
from app import models
from app.utils import upsert_time

router = APIRouter()

def _redis():
    return Redis.from_url(settings.redis_url)

@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    # First: try to fetch persisted job record
    rec = db.query(models.JobRun).filter(models.JobRun.job_id == job_id).one_or_none()

    # Second: try Redis for live status/result (best-effort)
    j = None
    try:
        j = Job.fetch(job_id, connection=_redis())
    except Exception:
        j = None

    if not rec and not j:
        raise HTTPException(404, "job not found")

    # Derive status
    status = None
    if j:
        raw = j.get_status()  # queued/started/finished/failed/deferred
        status = "queued" if raw in {"queued","deferred"} else raw
        if status not in {"queued","started","finished","failed"}:
            status = "queued"
    else:
        status = rec.status if rec else "queued"

    # session/user_message from redis meta if present, else db
    session_id = None
    user_message_id = None
    if j and j.meta:
        session_id = j.meta.get("session_id")
        user_message_id = j.meta.get("user_message_id")
    if not session_id and rec:
        session_id = rec.session_id
    if not user_message_id and rec:
        user_message_id = rec.user_message_id

    resp = {
        "job_id": job_id,
        "status": status,
        "session_id": session_id,
        "user_message_id": user_message_id,
        "result": None,
        "error": None,
    }

    now = datetime.now(timezone.utc)
    time_id = upsert_time(db, now)

    # Update persisted record from live job info (idempotent)
    if rec:
        if status != rec.status:
            rec.status = status
            if status == "started" and rec.started_at is None:
                rec.started_at = now
            if status in {"finished","failed"} and rec.finished_at is None:
                rec.finished_at = now

    if j and status == "finished":
        result = j.result or {}
        resp["result"] = result
        if rec:
            rec.result_json = result
            rec.error_json = {}

        # Record a completion fact (LLM output) once per message.
        # The worker returns artifacts (including generated macro code) but does not
        # write directly to the API database. Persisting this here ensures metrics
        # reflect both prompts and completions for end-to-end tests.
        if session_id and user_message_id:
            existing_completion = (
                db.query(models.FactCompletion)
                .filter(models.FactCompletion.session_id == session_id)
                .filter(models.FactCompletion.message_id == user_message_id)
                .one_or_none()
            )
            if existing_completion is None:
                arts_for_chars = (result.get("artifacts") or [])
                # Best-effort estimate of LLM output size: use the largest generated macro artifact.
                output_chars = 0
                for a in arts_for_chars:
                    if a.get("kind") == "freecad_macro_py":
                        try:
                            output_chars = max(output_chars, int(a.get("bytes") or 0))
                        except Exception:
                            continue
                try:
                    iterations = int(result.get("iterations") or 0)
                except Exception:
                    iterations = 0

                # Ensure the configured model exists to avoid FK issues in fresh DBs.
                # Model metadata is provided by Docker via environment variables.
                default_model_id = settings.model_id
                model_row = (
                    db.query(models.DimModel)
                    .filter(models.DimModel.model_id == default_model_id)
                    .one_or_none()
                )
                if model_row is None:
                    db.add(
                        models.DimModel(
                            model_id=default_model_id,
                            name=default_model_id,
                            backend=settings.model_backend,
                            device=settings.model_device,
                        )
                    )

                db.add(
                    models.FactCompletion(
                        session_id=session_id,
                        model_id=default_model_id,
                        time_id=time_id,
                        message_id=user_message_id,
                        output_chars=output_chars,
                        latency_ms=None,
                        repair_iterations=max(0, iterations - 1),
                    )
                )

        # Persist validation + issues and artifacts if result follows expected schema
        passed = bool(result.get("passed"))
        iterations = int(result.get("iterations", 0))
        issues = result.get("issues") or []
        # Write a log event
        if session_id:
            db.add(models.LogEvent(session_id=session_id, type="job.finished",
                                   payload_json={"job_id": job_id, "passed": passed, "iterations": iterations}))
        # Artifacts: create DimArtifact + FactArtifactEvent (object_key+kind de-dupe)
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
                created_at=now,
            ))
            if session_id and user_message_id:
                db.add(models.FactArtifactEvent(
                    artifact_id=art_id, session_id=session_id, time_id=time_id,
                    message_id=user_message_id, event_type="created"
                ))

        db.commit()

    if j and status == "failed":
        err = {"exc_info": str(j.exc_info)[:4000] if j.exc_info else "unknown error"}
        resp["error"] = err
        if rec:
            rec.error_json = err
            rec.result_json = {}
            rec.status = "failed"
            rec.finished_at = rec.finished_at or now
        if session_id:
            db.add(models.LogEvent(session_id=session_id, type="job.failed", payload_json={"job_id": job_id, "error": err}))
        db.commit()

    # If we only have persisted data (Redis missing)
    if not j and rec:
        if rec.status == "finished":
            resp["result"] = rec.result_json
        if rec.status == "failed":
            resp["error"] = rec.error_json

    return resp
