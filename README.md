# CAD Agent — Private, Local-First CAD Automation with FreeCAD

A fully self-hosted CAD assistant that generates, validates, repairs, and exports FreeCAD models using:

- Local LLMs (CPU or CUDA GPU)
- Headless FreeCAD validation
- Automatic constraint repair loop
- Authoritative RAG (pgvector)
- S3-compatible artifact storage (MinIO)
- Full audit logging and analytics-ready schema
- Unit and integration tests (pytest)
- CLI for day-to-day use

No OpenAI or third-party hosted LLMs are required.  
All prompts, models, documents, and artifacts stay on your machine or infrastructure.

---

## Architecture Overview

### Core components

- API: FastAPI (REST)
- Jobs: Redis + RQ
- Worker: FreeCAD (freecadcmd) headless execution
- LLM: Local OpenAI-compatible server (llama.cpp / vLLM)
- RAG: Postgres + pgvector
- Artifacts: MinIO (S3-compatible)
- Database: Postgres (star schema: facts and dimensions)

### High-level flow

1. User sends prompt to API
2. API enqueues background job
3. Worker:
   - calls local LLM
   - generates FreeCAD macro
   - runs headless FreeCAD validation
   - repairs constraints if needed
   - exports FCStd / STEP / STL
4. Artifacts stored in MinIO
5. Results queried via API or CLI

---

## Prerequisites

### Required

- Docker Desktop
  - Windows 11 (WSL2 backend recommended)
  - or Linux
- 8+ GB RAM (16 GB recommended)
- 20+ GB disk (FreeCAD worker image is large)

### Optional

- Git
- Python 3.10+ (for CLI and integration tests)
- curl or Postman

---

## Quick Start (CPU)

### 1. Provide a local LLM model

This project expects an OpenAI-compatible local LLM server.

For CPU:
- Use llama.cpp server
- Place a GGUF model at:

```
./models/model.gguf
```

Recommended CPU models:
- 3B–7B
- Quantized (Q4_K_M or smaller)

---

### 2. Start the stack

```bash
docker compose --profile cpu up --build
```

---

### 3. Initialize the database

```bash
docker compose run --rm api alembic upgrade head
```

---

### 4. Create a session

```bash
curl -X POST http://localhost:8080/v1/sessions \
  -H "Content-Type: application/json" \
  -d '{"title":"demo"}'
```

The response includes a session_id.

---

### 5. Send a prompt (async job)

```bash
curl -X POST http://localhost:8080/v1/sessions/<SESSION_ID>/messages \
  -H "Content-Type: application/json" \
  -d '{
    "content":"Create a parametric bracket with two mounting holes",
    "mode":"design",
    "export":{"fcstd":true,"step":true,"stl":false},
    "units":"mm",
    "tolerance_mm":0.1
  }'
```

Returns:
- job_id
- user_message_id

---

### 6. Poll job status

```bash
curl http://localhost:8080/v1/jobs/<JOB_ID>
```

Job statuses:
- queued
- started
- finished
- failed

Jobs persist in Postgres even if Redis restarts.

---

### 7. List artifacts for a session

```bash
curl http://localhost:8080/v1/sessions/<SESSION_ID>/artifacts
```

Artifacts include:
- FreeCAD macros
- Validation reports
- FCStd / STEP / STL exports

---

### 8. Download artifacts

```bash
curl http://localhost:8080/v1/artifacts/<ARTIFACT_ID>
```

Returns a presigned URL (MinIO / S3-compatible).

---

## Repair Loop

Each job runs:

1. Generate macro via local LLM
2. Run FreeCAD headless validation (freecadcmd)
3. Parse validation output
   - Sketch solver messages
   - Degree of Freedom (DoF)
   - Export failures
4. Repair if needed using a constraint-aware prompt
5. Retry (default: 3 iterations)

### Validation taxonomy

- CONSTRAINT_OVERCONSTRAINED
- CONSTRAINT_UNDERCONSTRAINED
- CONSTRAINT_REDUNDANT
- FREECAD_EXCEPTION
- EXPORT_FAILED

All iterations and reports are preserved.

---

## Sessions

### Create

```
POST /v1/sessions
```

### End (close)

```
POST /v1/sessions/{session_id}/end
```

### Fork (branch)

```
POST /v1/sessions/{session_id}/fork
```

Forking creates a new session that inherits context but diverges cleanly.

---

## RAG (Authoritative Knowledge Only)

### Configure sources

Edit:

```
rag_sources.yaml
```

Supports:
- allowlist
- blacklist
- trust tiers
- scholarly or official sources only

---

### Reconcile sources into the database

```bash
curl -X POST http://localhost:8080/v1/rag/sources/reconcile
```

All changes are logged for auditability.

---

### Query RAG

```bash
curl -X POST http://localhost:8080/v1/rag/query \
  -H "Content-Type: application/json" \
  -d '{"query":"FreeCAD sketch constraint best practices","top_k":8,"max_trust_tier":2}'
```

Uses pgvector inside Postgres.

---

## CLI Tool

Location:

```
tools/cad_agent_cli.py
```

Install dependencies on host:

```bash
pip install httpx
```

### CLI examples

Create session:
```bash
python tools/cad_agent_cli.py session create --title demo
```

Send prompt and wait:
```bash
python tools/cad_agent_cli.py prompt send \
  --session-id <SID> \
  --text "Create a mounting bracket" \
  --wait
```

Watch job:
```bash
python tools/cad_agent_cli.py job status --job-id <JOB_ID> --watch
```

List artifacts:
```bash
python tools/cad_agent_cli.py artifacts list --session-id <SID>
```

RAG:
```bash
python tools/cad_agent_cli.py rag reconcile
python tools/cad_agent_cli.py rag query --query "FreeCAD Sketcher solver"
```

---

## GPU Usage (Later)

On a CUDA-capable host:

```bash
docker compose --profile gpu \
  -f docker-compose.yml \
  -f docker-compose.gpu.override.yml up --build
```

Supported GPU backends:
- vLLM (OpenAI-compatible)
- llama.cpp CUDA

No API or code changes required.

---

## Testing

### Unit Tests

Location:
```
services/api/app/tests/
```

Run:

```bash
docker compose run --rm api pytest -q
```

Covers:
- API routes
- schema validation
- database logic
- job persistence

---

### Integration Tests (End-to-End)

Location:
```
tests/integration/
```

Requirements:
- Stack running on localhost
- Host Python

Install:
```bash
pip install -r tests/requirements.txt
```

Run:
```bash
pytest -m integration -q
```

Covers:
- session creation
- job enqueue
- repair loop execution
- artifact creation
- artifact listing

---

## What Is Not Tested Automatically

- Individual generated FreeCAD macros  
  These are validated via headless FreeCAD execution, not unit tests.
- Patent infringement  
  This system provides risk warnings only, not legal guarantees.

---

## License

See LICENSE.md  
(Proprietary / internal use)
