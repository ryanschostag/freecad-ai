from __future__ import annotations
import yaml
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text as sqltext
from urllib.parse import urlparse
from app.db import get_db
from app import models
from app.settings import settings
from app.utils import upsert_time, config_hash
from app.embeddings import embed_text_stub

router = APIRouter()

@router.post("/rag/sources/reconcile")
def reconcile_sources(db: Session = Depends(get_db)):
    with open(settings.rag_sources_config, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    now = datetime.now(timezone.utc)
    time_id = upsert_time(db, now)
    cfg_h = config_hash(cfg)
    desired = {s["source_id"]: s for s in (cfg.get("sources") or [])}
    existing = {s.source_id: s for s in db.query(models.DimSource).all()}
    added=[]; updated=[]; disabled=[]
    for sid, src in desired.items():
        eps = src.get("entrypoints") or []
        dom = urlparse(eps[0]).netloc if eps else None
        if sid not in existing:
            db.add(models.DimSource(
                source_id=sid, domain=dom, trust_tier=int(src.get("trust_tier",2)),
                kind=src.get("kind","crawl"), is_enabled=bool(src.get("enabled",True)),
                is_blacklisted=False, entrypoints_json=eps,
                include_patterns_json=src.get("include_patterns") or [],
                exclude_patterns_json=src.get("exclude_patterns") or [],
                license_note=src.get("license_note"), updated_at=now
            ))
            db.add(models.FactSourceChange(source_id=sid, time_id=time_id, change_type="added", actor_user_id="local",
                                           config_hash=cfg_h, notes="added from config"))
            added.append(sid)
        else:
            rec=existing[sid]; changed=False
            fields={
                "domain": dom or rec.domain,
                "trust_tier": int(src.get("trust_tier", rec.trust_tier)),
                "kind": src.get("kind", rec.kind),
                "is_enabled": bool(src.get("enabled", rec.is_enabled)),
                "entrypoints_json": eps,
                "include_patterns_json": src.get("include_patterns") or [],
                "exclude_patterns_json": src.get("exclude_patterns") or [],
                "license_note": src.get("license_note"),
            }
            for k,v in fields.items():
                if getattr(rec,k)!=v:
                    setattr(rec,k,v); changed=True
            if changed:
                rec.updated_at=now
                db.add(models.FactSourceChange(source_id=sid, time_id=time_id, change_type="updated", actor_user_id="local",
                                               config_hash=cfg_h, notes="updated from config"))
                updated.append(sid)
    for sid, rec in existing.items():
        if sid not in desired and rec.is_enabled:
            rec.is_enabled=False; rec.updated_at=now
            db.add(models.FactSourceChange(source_id=sid, time_id=time_id, change_type="disabled", actor_user_id="local",
                                           config_hash=cfg_h, notes="missing from config"))
            disabled.append(sid)
    db.commit()
    return {"added": added, "updated": updated, "disabled": disabled}

@router.post("/rag/query")
def rag_query(payload: dict, db: Session = Depends(get_db)):
    query = payload["query"]
    top_k = int(payload.get("top_k", 8))
    max_tier = int(payload.get("max_trust_tier", 2))
    qvec = embed_text_stub(query)
    sql = sqltext("""
      SELECT c.chunk_id, c.source_id, c.locator, c.text,
             (1.0 / (1.0 + (c.embedding <-> :qvec))) AS score
      FROM rag_chunks c
      JOIN dim_source s ON s.source_id = c.source_id
      WHERE s.is_enabled = true
        AND s.is_blacklisted = false
        AND s.trust_tier <= :max_tier
      ORDER BY c.embedding <-> :qvec
      LIMIT :k
    """)
    rows = db.execute(sql, {"qvec": qvec, "max_tier": max_tier, "k": top_k}).fetchall()
    return {"results":[{"chunk_id": r[0], "source_id": r[1], "locator": r[2], "text": r[3], "score": float(r[4])} for r in rows]}
