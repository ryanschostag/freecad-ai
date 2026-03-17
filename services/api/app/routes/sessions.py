from __future__ import annotations

import asyncio
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


LLM_LOADING_HINTS = (
    "loading model",
    "model is loading",
    "model loading",
    "loading",
    "initializing",
    "warm",
    "slot",
)


def _load_run_repair_loop_job():
    """Import the worker job entrypoint for inline test execution.

    In the test-runner container pytest imports the API package directly from
    /repo/services/api, which does not automatically put
    /repo/services/freecad-worker on sys.path. Defer the import and add the
    worker package root when needed so API tests can import app.main without the
    dedicated worker image layout.
    """
    try:
        from worker.jobs import run_repair_loop_job
        return run_repair_loop_job
    except ModuleNotFoundError as exc:
        if exc.name != "worker":
            raise

        import sys
        from pathlib import Path

        worker_root = Path(__file__).resolve().parents[3] / "freecad-worker"
        worker_root_str = str(worker_root)
        if worker_root_str not in sys.path:
            sys.path.insert(0, worker_root_str)

        from worker.jobs import run_repair_loop_job
        return run_repair_loop_job


def _response_text(response: object) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text
    content = getattr(response, "content", None)
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="ignore")
    if isinstance(content, str):
        return content
    return ""


async def ensure_llm_ready(max_wait_s: float | None = None) -> None:
    """Fail fast if the configured LLM is not reachable, with a warm-up retry window.

    Session creation can succeed before llama.cpp has finished loading the model.
    When the user immediately sends a prompt from the web UI, a short fixed probe
    spuriously fails even though the service is still loading. Retry for a longer,
    configurable warm-up window so prompt submission can return a job id reliably
    after startup on CPU hosts.
    """
    settings = Settings()
    base = (settings.llm_base_url or "").rstrip("/")
    if not base:
        raise HTTPException(status_code=503, detail="LLM_BASE_URL is not configured")

    effective_wait_s = float(
        max_wait_s if max_wait_s is not None else getattr(settings, "llm_ready_timeout_seconds", 300.0)
    )
    candidates = [f"{base}/health", f"{base}/v1/models", f"{base}/"]
    single_probe_timeout = max(2.0, float(getattr(settings, "llm_health_timeout_seconds", 2.0)))
    timeout = httpx.Timeout(single_probe_timeout, connect=min(single_probe_timeout, 5.0))
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.0, effective_wait_s)
    last_error: str | None = None

    async with httpx.AsyncClient(timeout=timeout) as client:
        while True:
            for url in candidates:
                try:
                    r = await client.get(url)
                    body = _response_text(r).lower()
                    if 200 <= r.status_code < 300:
                        return
                    if r.status_code in {408, 425, 429, 500, 502, 503, 504}:
                        if any(hint in body for hint in LLM_LOADING_HINTS):
                            last_error = f"{url} still warming up ({r.status_code})"
                        else:
                            last_error = f"{url} returned {r.status_code}"
                    else:
                        last_error = f"{url} returned {r.status_code}"
                except Exception as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
            if loop.time() >= deadline:
                break
            await asyncio.sleep(1.0)

    detail = f"LLM is not ready at {base} after waiting {effective_wait_s:.0f}s"
    if last_error:
        detail = f"{detail} ({last_error})"
    raise HTTPException(status_code=503, detail=detail)


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
    max_repair_iterations = int(payload.get("max_repair_iterations") or 3)
    llm_max_tokens = int(payload.get("llm_max_tokens") or 1200)

    # Gate job enqueue on LLM readiness so clients do not fail just because
    # the model is still finishing its startup warm-up window.
    await ensure_llm_ready()

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
            run_repair_loop_job = _load_run_repair_loop_job()
            result = run_repair_loop_job(
                job_id=job_id,
                session_id=session_id,
                user_message_id=user_message_id,
                prompt=content,
                mode=mode,
                export=export,
                units=units,
                tolerance_mm=tolerance_mm,
                max_repair_iterations=max_repair_iterations,
                llm_max_tokens=llm_max_tokens,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            finished_at = datetime.now(timezone.utc)
            job_run = db.query(models.JobRun).filter(models.JobRun.job_id == job_id).one()
            job_run.status = "failed"
            job_run.finished_at = finished_at
            job_run.error_json = {"detail": str(exc)}
            db.add(models.LogEvent(session_id=session_id, type="job.failed", payload_json={"job_id": job_id, "detail": str(exc)}))
            db.commit()
            raise
        else:
            finished_at = datetime.now(timezone.utc)
            job_run = db.query(models.JobRun).filter(models.JobRun.job_id == job_id).one()
            job_run.status = result.get("status", "finished")
            job_run.finished_at = finished_at
            job_run.result_json = result
            db.add(models.LogEvent(session_id=session_id, type="job.finished", payload_json={"job_id": job_id}))
            db.commit()
    else:
        q = get_queue()
        q.enqueue(
            "worker.jobs.run_repair_loop_job",
            job_id=job_id,
            session_id=session_id,
            user_message_id=user_message_id,
            prompt=content,
            mode=mode,
            export=export,
            units=units,
            tolerance_mm=tolerance_mm,
            max_repair_iterations=max_repair_iterations,
            llm_max_tokens=llm_max_tokens,
            timeout_seconds=timeout_seconds,
            job_timeout=rq_timeout_seconds,
            result_ttl=86400,
            failure_ttl=86400,
        )

    return {"job_id": job_id, "session_id": session_id, "status": "queued"}
