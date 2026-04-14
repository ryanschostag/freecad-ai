# FreeCAD AI

FreeCAD AI is a Docker-based application for turning natural-language CAD requests into FreeCAD execution jobs, tracked sessions, downloadable artifacts, and reusable training state.

It is designed to make the stack approachable from several entry points:
- a browser-based Web UI for interactive sessions and artifact downloads
- a FastAPI backend with documented REST endpoints
- a MinIO object-storage console for inspecting stored artifacts
- a Python CLI for scripting and diagnostics from the host machine
- a persisted LLM training-state workflow for carrying forward examples and retrieved guidance

## Why use FreeCAD AI

FreeCAD AI gives you a complete local development stack around FreeCAD-driven generation rather than only a single prompt interface.

Highlights:
- **Web UI** at `http://localhost:3000` for session creation, prompt submission, job tracking, log inspection, and artifact downloads
- **FastAPI Swagger UI** at `http://localhost:8080/docs` for interactive endpoint exploration
- **MinIO Console** at `http://localhost:9001` for browsing artifact storage in a web browser
- **Docker Compose profiles** for CPU, GPU, and deterministic test runs
- **CAD Agent CLI** for shell automation, diagnostics, and artifact retrieval
- **Persistent LLM state** stored in SQLite so training snapshots survive rebuilds and can be reused by the worker
- **Session and retry flow** that captures diagnostics, job history, and repair attempts

## Repository layout

```text
services/
  api/              FastAPI backend, queueing, metadata, RAG config reconciliation
  freecad-worker/   worker process, macro validation, FreeCAD execution, retry logic
  web-ui/           browser UI and API reverse proxy
  rag/              placeholder service docs for future expansion

tools/
  cad_agent/        host-side CLI client
  train_llm_state.py
  collect_logs.py
  fake_llm_server.py
  migrate_data_state_to_sqlite3.py

docs/               user and operator documentation
rag_sources.yaml    RAG source allowlist and trust policy
```

## Quick start

### 1. Configure environment

Copy `.env.sample` to `.env` and review the values that matter most for your machine:
- `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`
- `S3_ACCESS_KEY` / `S3_SECRET_KEY`
- `LLM_STATE_DIR` / `LLM_STATE_HOST_DIR`
- `LLM_MODEL_PATH`
- `LLM_CTX_SIZE`
- `LLM_ERROR_RETRY_LIMIT`

### 2. Start the stack

#### CPU profile

```bash
docker compose --profile cpu up -d --build
```

#### GPU profile

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.override.yml --profile gpu up -d --build
```

#### Test profile

```bash
docker compose -f docker-compose.yml -f docker-compose.test-override.yml --profile test up -d --build
```

### 3. Open the browser tools

For the CPU and GPU profiles:
- Web UI: `http://localhost:3000`
- API docs: `http://localhost:8080/docs`
- OpenAPI JSON: `http://localhost:8080/openapi.json`
- MinIO Console: `http://localhost:9001`

For the test profile:
- test API: `http://localhost:8081/docs`
- test Web UI: `http://localhost:3001`
- fake LLM host port: `http://localhost:8001`

## Web UI quick start

The Web UI is the fastest way to use the application without remembering session ids and job ids manually.

Typical flow:
1. Open `http://localhost:3000`
2. Click **Create new session**
3. Enter a prompt and choose export formats such as `fcstd`, `step`, or `stl`
4. Submit the request
5. Watch the **Job Tracker** panel until the job finishes or fails
6. Use **Session Logs** and **Artifacts** to inspect execution details and download results

The UI can also:
- load an existing session by session id
- fork a session
- fetch structured logs
- list artifacts for the current session
- request a presigned link for an artifact download

More detail: `docs/web-ui-readme.md`

## REST API

The backend is a FastAPI application that exposes health checks, sessions, jobs, logs, artifacts, RAG management, and worker-only internal job status callbacks.

Common endpoints:
- `GET /health`
- `GET /health/llm`
- `POST /v1/sessions`
- `POST /v1/sessions/{session_id}/fork`
- `POST /v1/sessions/{session_id}/messages`
- `GET /v1/jobs/{job_id}`
- `GET /v1/sessions/{session_id}/logs`
- `GET /v1/sessions/{session_id}/artifacts`
- `GET /v1/artifacts/{artifact_id}`
- `POST /v1/rag/query`
- `POST /v1/rag/sources/reconcile`

Worker callback endpoints used by the FreeCAD worker:
- `POST /internal/jobs/{job_id}/started`
- `POST /internal/jobs/{job_id}/retrying`
- `POST /internal/jobs/{job_id}/complete`

More detail: `docs/rest-api-readme.md`

## CAD Agent CLI

The host-side CLI lives at `tools/cad_agent/cad_agent_cli.py`. It is useful for health checks, session management, sending prompts, waiting on jobs, dumping debug payloads, and downloading artifacts without opening the Web UI.

Example:

```bash
python tools/cad_agent/cad_agent_cli.py health --llm
python tools/cad_agent/cad_agent_cli.py session create --title "demo"
python tools/cad_agent/cad_agent_cli.py message send   --session <SESSION_ID>   --prompt "Create a simple box 10mm x 20mm x 5mm"   --export fcstd,step
python tools/cad_agent/cad_agent_cli.py job wait --job <JOB_ID> --timeout-seconds 300
```

More detail: `docs/cad-agent-cli-readme.md`

## MinIO object storage and browser console

Artifacts are stored in S3-compatible object storage. In local development that storage is provided by MinIO.

What MinIO stores:
- generated macros
- diagnostics and runner status files
- exported CAD artifacts such as FCStd, STEP, and STL
- logs and auxiliary job outputs written by the API and worker flow

Default local endpoints:
- S3 API: `http://localhost:9000`
- MinIO Console: `http://localhost:9001`

More detail: `docs/minio-readme.md`

## Docker profiles

The repository is organized around Docker Compose profiles:
- **cpu**: local llama.cpp server and full application stack
- **gpu**: GPU-enabled llama.cpp path using the compose override
- **test**: deterministic fake-LLM path for Dockerized pytest runs

More detail: `docs/docker-readme.md`

## Persistent LLM state

FreeCAD AI persists reusable model state in a mounted directory, backed by a SQLite database.

Default paths:
- host: `./data/llm/state`
- container: `/data/llm/state`
- SQLite database file: `llm-state.sqlite3`

The worker and API mount the same state directory, allowing generated training snapshots to survive container rebuilds and restarts.

### What is stored

Each training run writes a logical run record into SQLite, including:
- `manifest_json`
- `inference_profile_json`
- `checkpoint_json`
- `optimizer_state_json`
- `weights_json`
- `lora_adapter_json`
- `embedding_index_json`
- optional imported binary artifacts
- a `state_latest` pointer that identifies the active run

The worker loads the latest `inference_profile_json` and uses it to inject persistent guidance into later LLM requests.

### Train a reusable state snapshot

```bash
python tools/train_llm_state.py --dataset docs/train_llm_state/minimal_dataset.json
```

The dataset can include:
- model metadata
- prompt/response examples
- inline documents
- document paths to repository files
- optional imported artifact paths from external training workflows

Comprehensive guide: `docs/train_llm_state/README.md`

## Configuration files

### `.env`

The `.env` file controls runtime behavior for the Docker stack, including MinIO credentials, LLM settings, retry limits, and persistent state directories.

### `rag_sources.yaml`

`rag_sources.yaml` defines the source catalog and policy used by RAG reconciliation.

It includes:
- default trust policy
- allowed and denied domains
- source ids and entrypoints
- include/exclude regex patterns
- license notes for each source

The API reads this file through `RAG_SOURCES_CONFIG=/config/rag_sources.yaml` and the reconcile endpoint can load its contents into the database-backed source dimension.

## Testing

The project is designed to run tests inside Docker using the `test` profile. The fake LLM, test API, worker, Redis, Postgres, and MinIO stack are all started together so test behavior matches the intended integration environment.

See `docs/testing.md` for the full test catalog and recommended commands.

## Operational notes

- The worker performs semantic validation for known bad macro patterns before execution.
- Jobs can transition through `queued`, `started`, `retrying`, `finished`, and `failed`.
- Retry flows can persist session-specific training snapshots after failures.
- Artifact retrieval is done with presigned URLs from the API.
- The RAG service directory is currently documentation-only; reconciliation and query endpoints live in the API service today.

## Documentation index

- `docs/web-ui-readme.md`
- `docs/minio-readme.md`
- `docs/docker-readme.md`
- `docs/rest-api-readme.md`
- `docs/cad-agent-cli-readme.md`
- `docs/operational-runbook.md`
- `docs/testing.md`
- `docs/train_llm_state/README.md`
- `docs/architecture.drawio`
- `docs/FreeCAD-AI_Technical_Documentation.docx`

## License

This repository is licensed under the MIT License. See `LICENSE.md`.
