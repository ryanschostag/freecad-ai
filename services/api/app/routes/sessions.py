from __future__ import annotations
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
import httpx
from sqlalchemy.orm import Session
from app.db import get_db
from app import models
from app.schemas import CreateSessionRequest
from app.utils import upsert_time
from app.queue import get_queue
from app.settings import Settings

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
def create_session(req: CreateSessionRequest | None = None, db: Session = Depends(get_db)):
    req = req or CreateSessionRequest()
    sid = str(uuid.uuid4())
    s = models.DimSession(
        session_id=sid, title=req.title, project_id=req.project_id, status="active",
        created_at=datetime.now(timezone.utc),
        preferences_json={}, latest_state_json={}
    )
    db.add(s); db.commit()
    db.add(models.LogEvent(session_id=sid, type="session.created", payload_json={"title": req.title}))
    db.commit()
    return {"session_id": sid, "parent_session_id": None, "title": req.title, "project_id": req.project_id,
            "status":"active", "created_at": s.created_at.isoformat(), "closed_at": None}

@router.post("/sessions/{session_id}/end")
def end_session(session_id: str, db: Session = Depends(get_db)):
    s = db.query(models.DimSession).filter(models.DimSession.session_id==session_id).one_or_none()
    if not s: raise HTTPException(404, "session not found")
    if s.status != "closed":
        s.status="closed"; s.closed_at=datetime.now(timezone.utc)
        db.add(models.LogEvent(session_id=session_id, type="session.closed", payload_json={}))
        db.commit()
    return {"session_id": s.session_id, "status": s.status, "created_at": s.created_at.isoformat(), "closed_at": s.closed_at.isoformat() if s.closed_at else None}

@router.post("/sessions/{session_id}/fork", status_code=201)
def fork_session(session_id: str, db: Session = Depends(get_db)):
    s = db.query(models.DimSession).filter(models.DimSession.session_id==session_id).one_or_none()
    if not s: raise HTTPException(404, "session not found")
    child = models.DimSession(
        session_id=str(uuid.uuid4()), parent_session_id=s.session_id,
        title=(s.title or "session")+" (fork)", project_id=s.project_id,
        status="active", created_at=datetime.now(timezone.utc),
        preferences_json=s.preferences_json, latest_state_json=s.latest_state_json
    )
    db.add(child); db.commit()
    db.add(models.LogEvent(session_id=child.session_id, type="session.forked", payload_json={"parent_session_id": s.session_id}))
    db.commit()
    return {"session_id": child.session_id, "parent_session_id": child.parent_session_id, "status": child.status,
            "created_at": child.created_at.isoformat(), "closed_at": None}

@router.post("/sessions/{session_id}/messages", status_code=202)
async def post_message(session_id: str, payload: dict, db: Session = Depends(get_db)):
    s = db.query(models.DimSession).filter(models.DimSession.session_id==session_id).one_or_none()
    if not s: raise HTTPException(404, "session not found")
    if s.status=="closed": raise HTTPException(409, "session is closed")

    content = payload["content"]
    mode = payload.get("mode","design")
    export = payload.get("export") or {"fcstd": True, "step": True, "stl": False}
    units = payload.get("units","mm")
    tolerance_mm = float(payload.get("tolerance_mm", 0.1))

    now = datetime.now(timezone.utc)
    time_id = upsert_time(db, now)
    user_message_id = str(uuid.uuid4())

    db.add(models.FactPrompt(session_id=session_id, user_id="local", time_id=time_id, message_id=user_message_id,
                             mode=mode, prompt_chars=len(content)))
    db.add(models.LogEvent(session_id=session_id, type="message.user",
                           payload_json={"message_id": user_message_id, "mode": mode}))
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
        # NOTE: RQ's Queue.enqueue_call uses `timeout` (seconds) for the job
        # execution limit. `job_timeout` is not a valid kwarg for our pinned
        # rq version and causes a 500/TypeError at enqueue time.
        timeout=rq_timeout_seconds,
        result_ttl=3600,
        failure_ttl=3600,
    )
    job.meta["session_id"] = session_id
    job.meta["user_message_id"] = user_message_id
    job.save_meta()

    # Persist job in Postgres so it survives Redis flushes
    db.add(models.JobRun(
        job_id=job_id,
        session_id=session_id,
        user_message_id=user_message_id,
        status="queued",
        enqueued_at=datetime.now(timezone.utc),
        result_json={},
        error_json={},
    ))
    db.commit()

    db.add(models.LogEvent(session_id=session_id, type="job.enqueued",
                           payload_json={"job_id": job_id, "message_id": user_message_id}))
    db.commit()

    # We return macro_artifact_id as a placeholder; actual artifacts are returned by /v1/jobs/{id}
    macro_artifact_id = str(uuid.uuid4())
    return {"job_id": job_id, "session_id": session_id, "user_message_id": user_message_id, "macro_artifact_id": macro_artifact_id}
