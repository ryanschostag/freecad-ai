# CAD Agent (local, private) — FreeCAD + RAG + Repair Loop

This repo runs a **private, local-first** CAD assistant:
- **API**: FastAPI (REST)
- **Jobs**: Redis queue + RQ worker
- **Worker**: headless `freecadcmd` execution + export (FCStd/STEP/STL)
- **Artifacts**: MinIO (S3-compatible) + **presigned URLs**
- **RAG**: Postgres + pgvector (authoritative allowlist/denylist)
- **Analytics**: Postgres star schema (facts/dimensions)

> No OpenAI or 3rd party hosted LLM services are required. You run your own LLM container (CPU or GPU) on your hardware.

---

## Quick start (CPU, Windows 11 Docker Desktop)

### 0) Prerequisites / dependencies
- Windows 11 + **Docker Desktop** (WSL2 backend recommended)
- Docker Desktop resources (recommended):
  - **8 CPUs**
  - **12–16 GB RAM**
  - **20+ GB disk free** (FreeCAD worker image is large)
- Optional:
  - Git
  - curl (or use Postman)

### 1) Provide a local model (CPU)
The `llm` container uses **llama.cpp server** and expects a GGUF model at:
- `models/model.gguf` (Docker volume `models`)

**Option A (recommended):** copy a GGUF file into the volume
- Create a folder `./models` at repo root
- Put your model at `./models/model.gguf`
- Update `docker-compose.yml` `llm` volume mount if you prefer a bind-mount

**Model size suggestions (CPU):**
- 3B–7B, quantized (e.g., Q4_K_M) is realistic on typical laptops.
- If responses are too slow, use a smaller model or lower context length.

### 2) Start services
```bash
docker compose --profile cpu up --build
```

### 3) Initialize DB
```bash
docker compose run --rm api alembic upgrade head
```

### 4) Create a session
```bash
curl -X POST http://localhost:8080/v1/sessions \
  -H "Content-Type: application/json" \
  -d '{"title":"demo"}'
```

### 5) Send a prompt (enqueues a job)
```bash
curl -X POST http://localhost:8080/v1/sessions/<SESSION_ID>/messages \
  -H "Content-Type: application/json" \
  -d '{
    "content":"Create a parametric bracket with 2 mounting holes and filleted corners",
    "mode":"design",
    "export":{"fcstd":true,"step":true,"stl":false},
    "units":"mm",
    "tolerance_mm":0.1
  }'
```

You will receive a `job_id`.

### 6) Poll job status
```bash
curl http://localhost:8080/v1/jobs/<JOB_ID>
```

When finished, `result.artifacts[]` contains object keys. To download via API:
- Find an artifact id in DB (or extend the API to list artifacts per session)
- Use `GET /v1/artifacts/{artifact_id}` to get a presigned URL.

---

## Repair loop behavior (end-to-end)
Each job runs:
1. **Generate** FreeCAD macro using local LLM (OpenAI-compatible endpoint)
2. Run **headless FreeCAD validation/export** (`freecadcmd`)
3. If validation fails, call LLM with a **constraint-aware repair prompt**
4. Retry up to `max_repair_iterations` (default: 3)

Worker writes validation reports to MinIO:
- `sessions/<session_id>/reports/<user_message_id>.validation.<iter>.json`

---

## GPU later (minimal changes)
A GPU host can use the `llm-gpu` profile (vLLM OpenAI-compatible server).

Example:
- `docker compose --profile gpu -f docker-compose.yml -f docker-compose.gpu.override.yml up --build`

Then set:
- `LLM_BASE_URL=http://llm-gpu:8000`

---

## RAG (pgvector) — allowlist/denylist
Edit `rag_sources.yaml` then run:
```bash
curl -X POST http://localhost:8080/v1/rag/sources/reconcile
```

Query retrieval:
```bash
curl -X POST http://localhost:8080/v1/rag/query \
  -H "Content-Type: application/json" \
  -d '{"query":"FreeCAD sketch constraints best practices","top_k":8,"max_trust_tier":2}'
```

---

## Tests
```bash
docker compose run --rm api pytest -q
```

---

## Notes
- The worker container installs FreeCAD via Ubuntu packages; it is intentionally “fat” so headless CAD is reliable.
- The LLM prompt format is designed to return **only Python macro code** (no markdown).
- For strict determinism, set model temperature low (already defaulted low in worker).

See also: `api_spec.yaml`
