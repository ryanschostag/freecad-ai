from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models
from app.db import get_db
from app.queue import get_queue
from app.schemas import CreateSessionRequest
from app.settings import Settings
from app.utils import upsert_time
from worker.jobs import run_repair_loop_job

router = APIRouter()


async def ensure_llm_ready() -> None:
    """Fail fast if the configured LLM is not reachable.

    The local llama.cpp server may or may not expose a dedicated /health endpoint
    depending on build flags. We try a small set of common endpoints.
    """
    settings = Settings()
    base = (settings.llm_base_url or "").rstrip("/")
    if not base:
        raise HTTPException(status_code=503, detail="LLM_BASE_URL is not configured")

    candidates = [f"{base}/health", f"{base}/v1/models", f"{base}/"]
    timeout = httpx.Timeout(2.0, connect=2.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for url in candidates:
            try:
                r = await client.get(url)
                if 200 <= r.status_code < 300:
                    return
            except Exception:
                continue
    raise HTTPException(status_code=503, detail=f"LLM is not ready at {base}")


def _get_session_or_404(db: Session, session_id: str) -> models.DimSession:
    s = db.query(models.DimSession).filter(models.DimSession.session_id == session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="session not found")
    return s


@router.post("/sessions", status_code=201)
def create_session(payload: CreateSessionRequest, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    upsert_time(db, now)

    session_id = str(uuid.uuid4())
    db.add(
        models.DimSession(
            session_id=session_id,
            parent_session_id=None,
            project_id=None,
            title=payload.title or "Untitled",
            status="active",
            created_at=now,
            closed_at=None,
            preferences_json={},
            latest_state_json={},
        )
    )
    db.add(models.LogEvent(session_id=session_id, type="session.created", payload_json={"title": payload.title}))
    db.commit()
    return db.query(models.DimSession).filter(models.DimSession.session_id == session_id).first()


@router.post("/sessions/{session_id}/fork", status_code=201)
def fork_session(session_id: str, db: Session = Depends(get_db)):
    parent = _get_session_or_404(db, session_id)
    if parent.status != "active":
        raise HTTPException(status_code=409, detail="session is not active")

    now = datetime.now(timezone.utc)
    upsert_time(db, now)

    child_id = str(uuid.uuid4())
    db.add(
        models.DimSession(
            session_id=child_id,
            parent_session_id=parent.session_id,
            project_id=parent.project_id,
            title=parent.title,
            status="active",
            created_at=now,
            closed_at=None,
            preferences_json=parent.preferences_json or {},
            latest_state_json=parent.latest_state_json or {},
        )
    )
    db.add(
        models.LogEvent(
            session_id=child_id,
            type="session.forked",
            payload_json={"parent_session_id": parent.session_id},
        )
    )
    db.commit()
    return db.query(models.DimSession).filter(models.DimSession.session_id == child_id).first()




@router.post("/sessions/{session_id}/end")
def end_session(session_id: str, db: Session = Depends(get_db)):
    session = _get_session_or_404(db, session_id)
    if session.status == "closed":
        return session

    now = datetime.now(timezone.utc)
    upsert_time(db, now)

    session.status = "closed"
    session.closed_at = now
    db.add(
        models.LogEvent(
            session_id=session_id,
            type="session.closed",
            payload_json={"closed_at": now.isoformat()},
        )
    )
    db.commit()
    db.refresh(session)
    return session

@router.post("/sessions/{session_id}/messages", status_code=202)
async def send_message(session_id: str, payload: dict, db: Session = Depends(get_db)):
    session = _get_session_or_404(db, session_id)
    if session.status != "active":
        raise HTTPException(status_code=409, detail="session is not active")

    # Backwards compatible: tests and older clients send {"content": "..."}.
    raw = payload.get("prompt")
    if raw is None:
        raw = payload.get("content")
    content = str(raw or "").strip()
    if not content:
        raise HTTPException(status_code=422, detail="prompt/content is required")

    mode = str(payload.get("mode") or "design")
    export = payload.get("export") or {}
    units = str(payload.get("units") or "mm")
    tolerance_mm = float(payload.get("tolerance_mm", 0.1))

    now = datetime.now(timezone.utc)
    time_id = upsert_time(db, now)
    user_message_id = str(uuid.uuid4())

    db.add(
        models.FactPrompt(
            session_id=session_id,
            user_id="local",
            time_id=time_id,
            message_id=user_message_id,
            mode=mode,
            prompt_chars=len(content),
        )
    )
    db.add(
        models.LogEvent(
            session_id=session_id,
            type="message.user",
            payload_json={"message_id": user_message_id, "mode": mode},
        )
    )
    db.commit()

    # Gate job enqueue on LLM readiness so clients fail fast instead of hanging.
    await ensure_llm_ready()

    settings = Settings()
    timeout_seconds = int(payload.get("timeout_seconds") or settings.default_job_timeout_seconds)
    rq_timeout_seconds = timeout_seconds + settings.job_timeout_buffer_seconds

    job_id = str(uuid.uuid4())

    # NOTE: The repo model is JobRun (job_runs), not FactJob.
    job_run = models.JobRun(
        job_id=job_id,
        session_id=session_id,
        user_message_id=user_message_id,
        status="queued",
        enqueued_at=now,
        started_at=None,
        finished_at=None,
        error_json={},
        result_json={},
    )
    db.add(job_run)
    db.add(models.LogEvent(session_id=session_id, type="job.queued", payload_json={"job_id": job_id}))
    db.commit()

    if settings.inline_jobs:
        started_at = datetime.now(timezone.utc)
        job_run = db.query(models.JobRun).filter(models.JobRun.job_id == job_id).one()
        job_run.status = "started"
        job_run.started_at = started_at
        db.commit()
        try:
            result = run_repair_loop_job(
                job_id=job_id,
                session_id=session_id,
                user_message_id=user_message_id,
                prompt=content,
                mode=mode,
                export=export,
                units=units,
                tolerance_mm=tolerance_mm,
                max_repair_iterations=3,
                timeout_seconds=timeout_seconds,
            )
            finished_at = datetime.now(timezone.utc)
            job_run = db.query(models.JobRun).filter(models.JobRun.job_id == job_id).one()
            job_run.status = "finished"
            job_run.finished_at = finished_at
            job_run.result_json = result
            job_run.error_json = {}
            db.commit()
        except Exception as exc:
            finished_at = datetime.now(timezone.utc)
            job_run = db.query(models.JobRun).filter(models.JobRun.job_id == job_id).one()
            job_run.status = "failed"
            job_run.finished_at = finished_at
            job_run.result_json = {}
            job_run.error_json = {"exc_info": f"{type(exc).__name__}: {exc}"}
            db.add(models.LogEvent(session_id=session_id, type="job.failed", payload_json={"job_id": job_id, "error": job_run.error_json}))
            db.commit()
    else:
        q = get_queue("freecad")

        # IMPORTANT:
        # Do NOT enqueue a callable here. In our current container mix, rq serializes the
        # callable into a colon-form reference (e.g. "worker:jobs.run_repair_loop_job"),
        # and the worker's rq import resolver (import_attribute) cannot resolve that form.
        # Enqueue a dotted string path instead, which the worker can import consistently.
        job = q.enqueue_call(
            func="worker.jobs.run_repair_loop_job",
            kwargs={
                "job_id": job_id,
                "session_id": session_id,
                "user_message_id": user_message_id,
                "prompt": content,
                "mode": mode,
                "export": export,
                "units": units,
                "tolerance_mm": tolerance_mm,
                "max_repair_iterations": 3,
                "timeout_seconds": timeout_seconds,
            },
            job_id=job_id,
            timeout=rq_timeout_seconds,
            result_ttl=3600,
            failure_ttl=3600,
        )
        job.meta["session_id"] = session_id
        job.meta["user_message_id"] = user_message_id
        job.save_meta()

    return {
        "job_id": job_id,
        "session_id": session_id,
        "user_message_id": user_message_id,
        "macro_artifact_id": None,
    }
