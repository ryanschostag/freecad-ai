import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db import get_db
from app import models
from app.schemas import CreateSessionRequest, SessionOut, CreateMessageRequest, CreateMessageResponse, MessageOut, ArtifactOut, CitationOut, ValidationSummary
from app.utils import upsert_time
import httpx
from app.settings import settings
import os, pathlib, hashlib, json

router = APIRouter()

def _sha256_bytes(b: bytes) -> str:
    import hashlib
    h=hashlib.sha256()
    h.update(b)
    return h.hexdigest()

@router.post("/sessions", response_model=SessionOut, status_code=201)
def create_session(req: CreateSessionRequest | None = None, db: Session = Depends(get_db)):
    req = req or CreateSessionRequest()
    s = models.DimSession(
        session_id=str(uuid.uuid4()),
        title=req.title,
        project_id=req.project_id,
        status="active",
        preferences_json=(req.preferences.model_dump() if req.preferences else {}),
        latest_state_json={}
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    # log
    db.add(models.LogEvent(session_id=s.session_id, type="session.created", payload_json={"title": req.title}))
    db.commit()
    return SessionOut(
        session_id=uuid.UUID(s.session_id),
        parent_session_id=uuid.UUID(s.parent_session_id) if s.parent_session_id else None,
        project_id=s.project_id,
        title=s.title,
        status=s.status,
        created_at=s.created_at.replace(tzinfo=timezone.utc),
        closed_at=s.closed_at.replace(tzinfo=timezone.utc) if s.closed_at else None
    )

@router.get("/sessions/{session_id}")
def get_session(session_id: str, db: Session = Depends(get_db)):
    s = db.query(models.DimSession).filter(models.DimSession.session_id==session_id).one_or_none()
    if not s:
        raise HTTPException(404, "session not found")
    msgs = db.query(models.LogEvent).filter(models.LogEvent.session_id==session_id).order_by(models.LogEvent.ts.desc()).limit(5).all()
    return {
        "session_id": s.session_id,
        "parent_session_id": s.parent_session_id,
        "project_id": s.project_id,
        "title": s.title,
        "status": s.status,
        "created_at": s.created_at,
        "closed_at": s.closed_at,
        "latest_state": s.latest_state_json,
        "recent_events": [{"type":m.type,"ts":m.ts,"payload":m.payload_json} for m in msgs],
    }

@router.post("/sessions/{session_id}/end", response_model=SessionOut)
def end_session(session_id: str, db: Session = Depends(get_db)):
    s = db.query(models.DimSession).filter(models.DimSession.session_id==session_id).one_or_none()
    if not s:
        raise HTTPException(404, "session not found")
    if s.status == "closed":
        return SessionOut(session_id=uuid.UUID(s.session_id), parent_session_id=uuid.UUID(s.parent_session_id) if s.parent_session_id else None,
                          project_id=s.project_id,title=s.title,status=s.status,created_at=s.created_at.replace(tzinfo=timezone.utc),
                          closed_at=s.closed_at.replace(tzinfo=timezone.utc) if s.closed_at else None)
    s.status = "closed"
    s.closed_at = datetime.now(timezone.utc)
    db.add(models.LogEvent(session_id=session_id, type="session.closed", payload_json={}))
    db.commit()
    db.refresh(s)
    return SessionOut(session_id=uuid.UUID(s.session_id), parent_session_id=uuid.UUID(s.parent_session_id) if s.parent_session_id else None,
                      project_id=s.project_id,title=s.title,status=s.status,created_at=s.created_at.replace(tzinfo=timezone.utc),
                      closed_at=s.closed_at.replace(tzinfo=timezone.utc) if s.closed_at else None)

@router.post("/sessions/{session_id}/fork", response_model=SessionOut, status_code=201)
def fork_session(session_id: str, db: Session = Depends(get_db)):
    s = db.query(models.DimSession).filter(models.DimSession.session_id==session_id).one_or_none()
    if not s:
        raise HTTPException(404, "session not found")
    child_id = str(uuid.uuid4())
    child = models.DimSession(
        session_id=child_id,
        parent_session_id=s.session_id,
        project_id=s.project_id,
        title=(s.title or "session") + " (fork)",
        status="active",
        preferences_json=s.preferences_json,
        latest_state_json=s.latest_state_json,
    )
    db.add(child)
    db.add(models.LogEvent(session_id=child_id, type="session.forked", payload_json={"parent_session_id": s.session_id}))
    db.commit()
    db.refresh(child)
    return SessionOut(session_id=uuid.UUID(child.session_id), parent_session_id=uuid.UUID(child.parent_session_id),
                      project_id=child.project_id,title=child.title,status=child.status,
                      created_at=child.created_at.replace(tzinfo=timezone.utc), closed_at=None)

@router.post("/sessions/{session_id}/messages", response_model=CreateMessageResponse)
def post_message(session_id: str, req: CreateMessageRequest, db: Session = Depends(get_db)):
    s = db.query(models.DimSession).filter(models.DimSession.session_id==session_id).one_or_none()
    if not s:
        raise HTTPException(404, "session not found")
    if s.status == "closed":
        raise HTTPException(409, "session is closed")

    user_msg_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    time_id = upsert_time(db, now)

    # Record fact_prompt
    db.add(models.FactPrompt(session_id=session_id, user_id="local", time_id=time_id, message_id=user_msg_id,
                             mode=req.mode, prompt_chars=len(req.content)))

    db.add(models.LogEvent(session_id=session_id, type="message.user", payload_json={"message_id": user_msg_id, "mode": req.mode}))
    db.commit()

    # ---- LLM (stub) ----
    # For scaffolding, we don't depend on actual model availability.
    # In production this would call the LLM backend and toolchain.
    assistant_text = (
        "STUB RESPONSE: I will generate a FreeCAD macro for your request. "
        "In this scaffold, the LLM + FreeCAD validation pipeline is mocked."
    )

    asst_msg_id = str(uuid.uuid4())
    db.add(models.FactCompletion(session_id=session_id, model_id="cpu-default", time_id=time_id, message_id=asst_msg_id,
                                 output_chars=len(assistant_text), latency_ms=1, repair_iterations=0))
    db.add(models.LogEvent(session_id=session_id, type="message.assistant", payload_json={"message_id": asst_msg_id}))
    db.commit()

    # Create a placeholder macro artifact on mounted folder
    artifact_dir = pathlib.Path(settings.artifact_dir) / session_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    macro_path = artifact_dir / "model.py"
    macro_contents = f'''# Auto-generated FreeCAD macro (stub)
# Session: {session_id}
# Message: {asst_msg_id}

def build():
    # TODO: implement with real FreeCAD API calls
    return "ok"
'''
    macro_bytes = macro_contents.encode("utf-8")
    macro_path.write_bytes(macro_bytes)
    sha = _sha256_bytes(macro_bytes)

    art_id = str(uuid.uuid4())
    dim_art = models.DimArtifact(
        artifact_id=art_id,
        kind="freecad_macro_py",
        storage_provider="localfs",
        object_key=str(macro_path),
        sha256=sha,
        bytes=len(macro_bytes)
    )
    db.add(dim_art)
    db.add(models.FactArtifactEvent(artifact_id=art_id, session_id=session_id, time_id=time_id, message_id=asst_msg_id, event_type="created"))
    db.commit()

    # Validation stub: always skipped
    db.add(models.FactValidationResult(session_id=session_id, time_id=time_id, message_id=asst_msg_id, passed=False, iteration_index=0, issues_count=0))
    db.commit()

    return CreateMessageResponse(
        session_id=uuid.UUID(session_id),
        message_id=uuid.UUID(asst_msg_id),
        assistant_message=MessageOut(message_id=uuid.UUID(asst_msg_id), role="assistant", content=assistant_text, created_at=now),
        artifacts=[ArtifactOut(artifact_id=uuid.UUID(art_id), kind="freecad_macro_py", path=str(macro_path), created_at=now, sha256=sha, bytes=len(macro_bytes))],
        citations=[],
        validation=ValidationSummary(status="skipped", iterations=0, issues=[])
    )
