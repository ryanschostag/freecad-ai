import hashlib, json
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app import models

def upsert_time(db: Session, ts: datetime) -> int:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ts = ts.astimezone(timezone.utc).replace(microsecond=0)
    existing = db.query(models.DimTime).filter(models.DimTime.ts == ts).one_or_none()
    if existing:
        return existing.time_id
    rec = models.DimTime(ts=ts)
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec.time_id

def config_hash(obj: dict) -> str:
    raw = json.dumps(obj, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
