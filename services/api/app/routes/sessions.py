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


@router.post("/sessions", status_code=201)
def create_session(payload: CreateSessionRequest, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    time_id = upsert_time(db, now)

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


@router.post("/sessions/{session_id}/messages", status_code=202)
async def send_message(session_id: str, payload: dict, db: Session = Depends(get_db)):
    content = str(payload.get("prompt") or "")
    if not content:
        raise HTTPException(status_code=422, detail="prompt is required")

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

    # Allow callers to override how long the job is allowed to run.
    # We add a small buffer to the RQ job timeout so internal timeouts
    # (LLM call / FreeCAD exec) can fail cleanly first.
    settings = Settings()
    timeout_seconds = int(payload.get("timeout_seconds") or settings.default_job_timeout_seconds)
    rq_timeout_seconds = timeout_seconds + settings.job_timeout_buffer_seconds

    q = get_queue("freecad")
    job_id = str(uuid.uuid4())

    # IMPORTANT: Use a string func reference instead of importing worker.jobs here.
    # These API tests run the FastAPI app inside the pytest container, which does
    # not include the worker package on sys.path. Importing worker.jobs would raise
    # ModuleNotFoundError and fail test_session_flow before enqueueing the job.
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

    db.add(
        models.FactJob(
            job_id=job_id,
            session_id=session_id,
            user_message_id=user_message_id,
            status="queued",
            created_at=now,
            started_at=None,
            finished_at=None,
            error_json=None,
            result_json=None,
        )
    )
    db.add(models.LogEvent(session_id=session_id, type="job.queued", payload_json={"job_id": job_id}))
    db.commit()

    return {
        "job_id": job_id,
        "session_id": session_id,
        "user_message_id": user_message_id,
        "macro_artifact_id": None,
    }
