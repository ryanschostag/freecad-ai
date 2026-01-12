from __future__ import annotations
import re
import yaml
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db import get_db
from app import models
from app.settings import settings
from app.utils import upsert_time, config_hash
from urllib.parse import urlparse

router = APIRouter()

@router.get("/rag/sources")
def list_sources(db: Session = Depends(get_db)):
    recs = db.query(models.DimSource).order_by(models.DimSource.source_id.asc()).all()
    return {"sources":[
        {
            "source_id": r.source_id,
            "enabled": r.is_enabled,
            "blacklisted": r.is_blacklisted,
            "trust_tier": r.trust_tier,
            "kind": r.kind,
            "entrypoints": r.entrypoints_json,
            "include_patterns": r.include_patterns_json,
            "exclude_patterns": r.exclude_patterns_json,
            "license_note": r.license_note,
        } for r in recs
    ]}

@router.post("/rag/sources/reconcile")
def reconcile_sources(db: Session = Depends(get_db)):
    # Reads rag_sources.yaml from mounted config and reconciles into DB,
    # logging new/updated/disabled into fact_source_change.
    with open(settings.rag_sources_config, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    now = datetime.now(timezone.utc)
    time_id = upsert_time(db, now)
    cfg_h = config_hash(cfg)

    desired = {}
    for src in (cfg.get("sources") or []):
        sid = src["source_id"]
        desired[sid] = src

    existing = {s.source_id: s for s in db.query(models.DimSource).all()}

    added, updated, disabled = [], [], []

    # upsert desired
    for sid, src in desired.items():
        dom = None
        eps = src.get("entrypoints") or []
        if eps:
            dom = urlparse(eps[0]).netloc
        if sid not in existing:
            rec = models.DimSource(
                source_id=sid,
                domain=dom,
                trust_tier=int(src.get("trust_tier", 2)),
                kind=src.get("kind","crawl"),
                is_enabled=bool(src.get("enabled", True)),
                is_blacklisted=False,
                entrypoints_json=eps,
                include_patterns_json=src.get("include_patterns") or [],
                exclude_patterns_json=src.get("exclude_patterns") or [],
                license_note=src.get("license_note"),
                updated_at=now,
            )
            db.add(rec)
            db.add(models.FactSourceChange(source_id=sid, time_id=time_id, change_type="added",
                                          actor_user_id="local", config_hash=cfg_h, notes="added from config"))
            added.append(sid)
        else:
            rec = existing[sid]
            changed = False
            fields = {
                "trust_tier": int(src.get("trust_tier", rec.trust_tier)),
                "kind": src.get("kind", rec.kind),
                "is_enabled": bool(src.get("enabled", rec.is_enabled)),
                "entrypoints_json": eps,
                "include_patterns_json": src.get("include_patterns") or [],
                "exclude_patterns_json": src.get("exclude_patterns") or [],
                "license_note": src.get("license_note"),
                "domain": dom or rec.domain,
            }
            for k,v in fields.items():
                if getattr(rec, k) != v:
                    setattr(rec, k, v)
                    changed = True
            if changed:
                rec.updated_at = now
                db.add(models.FactSourceChange(source_id=sid, time_id=time_id, change_type="updated",
                                              actor_user_id="local", config_hash=cfg_h, notes="updated from config"))
                updated.append(sid)

    # disable missing
    for sid, rec in existing.items():
        if sid not in desired and rec.is_enabled:
            rec.is_enabled = False
            rec.updated_at = now
            db.add(models.FactSourceChange(source_id=sid, time_id=time_id, change_type="disabled",
                                          actor_user_id="local", config_hash=cfg_h, notes="missing from config"))
            disabled.append(sid)

    db.commit()
    return {"added": added, "updated": updated, "disabled": disabled}

@router.post("/rag/ingest-runs", status_code=202)
def trigger_ingest_run(db: Session = Depends(get_db)):
    # Stub: in production, enqueue crawl/download/index job.
    import uuid
    run_id = str(uuid.uuid4())
    db.add(models.LogEvent(session_id="00000000-0000-0000-0000-000000000000", type="rag.ingest.triggered", payload_json={"run_id": run_id}))
    db.commit()
    return {"run_id": run_id, "status":"queued", "created_at": datetime.now(timezone.utc).isoformat(), "summary": {}}
