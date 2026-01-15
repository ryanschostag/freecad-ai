# FreeCAD‑AI

This repository provides a **working local pipeline** for generating CAD artifacts (FreeCAD `.FCStd`, STEP, STL) from natural‑language prompts using:

* A FastAPI backend (`api`)
* An RQ/Redis worker that runs FreeCAD logic (`freecad-worker`)
* A local LLM served via `llama.cpp` (`llm`, CPU profile)
* Postgres (with pgvector), Redis, and MinIO for persistence

The system is **functional and tested end‑to‑end**. This README documents the *current, verified state* — not aspirational features.

---

## Current Status (Important)

**What works today**

* Docker Compose setup with `cpu` profile
* Local GGUF LLM via `llama.cpp` HTTP server
* Session creation via REST API
* Job enqueue via REST API
* RQ worker executes jobs successfully
* LLM is queried correctly from the worker
* Integration test passes end‑to‑end (`pytest tests/integration`)
* Artifacts are generated and stored

**What is intentionally NOT done yet**

* No LLM health‑gating before job enqueue
* Job results currently live in Redis only (TTL‑based)
* Job state transitions are functional but not strictly enforced
* No lightweight / fake LLM test profile yet

These are planned next steps and **not bugs**.

---

## Requirements

* Docker Desktop (Windows / macOS / Linux)
* ~8–16 GB RAM recommended for 7B GGUF models
* A GGUF LLM file (see below)

---

## LLM Model Setup (Required)

This project **does not ship a model**. You must supply one.

### Supported format

* **GGUF** (required)
* Compatible with `llama.cpp` HTTP server

### Recommended models (known to work)

* Qwen2.5‑Coder‑7B‑Instruct‑Q4_K_M.gguf
* Code‑oriented instruct models work best

### Where the model goes

Create a directory at the repo root:

```
models/
  Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf
```

The file **does not** need to be renamed to `model.gguf`.

---

## Docker Compose

### CPU profile (normal usage)

```
docker compose --profile cpu up -d --build
```

This starts:

* `api` → [http://localhost:8080](http://localhost:8080)
* `llm` → [http://localhost:8000](http://localhost:8000)
* `freecad-worker`
* `db`, `redis`, `minio`

### Verify services

```
docker compose ps
```

You should see all services **Up**, and `llm` should *not* be restarting.

---

## API Usage

### Create a session

```
POST http://localhost:8080/v1/sessions

{
  "title": "itest"
}
```

Response:

```
201
{
  "session_id": "<uuid>",
  "status": "active"
}
```

---

### Enqueue a job

```
POST /v1/sessions/{session_id}/messages

{
  "content": "Create a simple box 10mm x 20mm x 5mm",
  "mode": "design",
  "units": "mm",
  "tolerance_mm": 0.1,
  "export": {
    "fcstd": true,
    "step": true,
    "stl": false
  }
}
```

Response:

```
202
{
  "job_id": "<uuid>"
}
```

---

### Poll job status

```
GET /v1/jobs/{job_id}
```

States observed in practice:

* `queued`
* `started`
* `finished`
* `failed`

A successful job eventually returns `finished`.

---

## CLI Tool

`tools/cad_agent_cli.py` can be used to create sessions and enqueue jobs.

Example:

```
python tools/cad_agent_cli.py session create \
  --title "test session" \
  --project-id "1234"
```

The CLI currently assumes:

* API is reachable
* LLM is healthy

(Health checks will be added later.)

---

## Testing

### Integration test (real LLM)

```
pytest -vv --full-trace tests
```

Notes:

* Uses **real LLM inference**
* Test duration: ~2–3 minutes
* This is expected and normal

### Passing output example

```
1 passed in ~180s
```

---

## Common Debugging

### LLM keeps restarting

Check logs:

```
docker compose logs -f llm
```

If you see:

```
failed to open GGUF file '/models/...'
```

Then:

* The file path is wrong **or**
* The model file is not readable **or**
* The volume mount is incorrect

Ensure:

```
volumes:
  - ./models:/models:ro
```

---

### Job stuck in `started`

This usually means:

* The worker finished
* But job state persistence was interrupted (Redis TTL, restart)

A restart typically resolves this. Result persistence will be improved later.

---

## Architecture Notes

* Redis is currently the **only job state store**
* Job results are ephemeral
* MinIO is used for artifact storage
* Postgres stores metadata, sessions, messages

This is intentional for the current phase.

---

## Planned Next Steps (Not Implemented Yet)

* LLM `/health` endpoint + job enqueue gating
* Strict job state transitions
* Persist job results outside Redis (DB / S3)
* Lightweight `test` profile with fake LLM

These will be added **incrementally**.

---

## Key Takeaway

If you can run:

```
docker compose --profile cpu up -d
pytest tests/integration
```

…and the test passes — your system is correctly set up.
