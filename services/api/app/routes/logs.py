import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.db import get_db
from app import models

router = APIRouter()

@router.get("/sessions/{session_id}/logs")
def get_logs(session_id: str, since: datetime | None = Query(default=None), db: Session = Depends(get_db)):
    s = db.query(models.DimSession).filter(models.DimSession.session_id==session_id).one_or_none()
    if not s: raise HTTPException(404, "session not found")
    q = db.query(models.LogEvent).filter(models.LogEvent.session_id==session_id)
    if since: q = q.filter(models.LogEvent.ts >= since)
    evs = q.order_by(models.LogEvent.ts.asc()).limit(5000).all()
    return {"events":[{"event_id": str(uuid.UUID(e.event_id)), "session_id": str(uuid.UUID(e.session_id)),
                       "ts": e.ts.isoformat(), "type": e.type, "payload": e.payload_json} for e in evs]}

@router.get("/sessions/{session_id}/metrics")
def get_metrics(session_id: str, db: Session = Depends(get_db)):
    s = db.query(models.DimSession).filter(models.DimSession.session_id==session_id).one_or_none()
    if not s: raise HTTPException(404, "session not found")
    return {
        "session_id": session_id,
        "prompts": db.query(models.FactPrompt).filter(models.FactPrompt.session_id==session_id).count(),
        "completions": db.query(models.FactCompletion).filter(models.FactCompletion.session_id==session_id).count(),
        "validations": db.query(models.FactValidationResult).filter(models.FactValidationResult.session_id==session_id).count(),
    }
