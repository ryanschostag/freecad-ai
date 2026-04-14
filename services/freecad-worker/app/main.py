from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime, timezone
import json, os
from jsonschema import validate
from pathlib import Path

app = FastAPI(title="FreeCAD Worker (stub)", version="0.1.0")

SCHEMA_PATH = "/app/app/worker_job.schema.json"

class Job(BaseModel):
    job_id: UUID
    session_id: UUID
    message_id: UUID | None = None
    kind: str
    inputs: dict
    output: dict
    limits: dict

@app.get("/v1/health")
def health():
    return {"status":"ok"}

@app.post("/v1/jobs")
def run_job(job: Job):
    # Validate against schema (strict contract)
    schema = json.loads(Path(SCHEMA_PATH).read_text(encoding="utf-8"))
    validate(instance=job.model_dump(), schema=schema)

    # Stubbed: pretend validation passed and create a report file.
    reports_dir = Path(job.output["reports_dir"])
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "validation.json"
    report = {
        "job_id": str(job.job_id),
        "status": "done",
        "validation": {"passed": True, "issues": []},
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return {
        "job_id": str(job.job_id),
        "status": "done",
        "validation": {"passed": True, "issues": []},
        "artifacts": [{"kind":"validation_report_json","path": str(report_path)}],
    }
