# REST API

The backend is a FastAPI application in `services/api`. It exposes session management, job tracking, logs, artifacts, health checks, and RAG-related routes.

## Interactive docs

- Swagger UI: `http://localhost:8080/docs`
- ReDoc: `http://localhost:8080/redoc`
- OpenAPI JSON: `http://localhost:8080/openapi.json`

Use the test API on port `8081` when the `test` profile is running.

## Core endpoint groups

### Health
- `GET /health`
- `GET /health/llm`

### Sessions
- `POST /v1/sessions`
- `POST /v1/sessions/{session_id}/fork`
- `POST /v1/sessions/{session_id}/end`
- `POST /v1/sessions/{session_id}/messages`
- `GET /v1/sessions/{session_id}/logs`
- `GET /v1/sessions/{session_id}/metrics`
- `GET /v1/sessions/{session_id}/artifacts`

### Jobs
- `GET /v1/jobs/{job_id}`

### Artifacts
- `GET /v1/artifacts/{artifact_id}`
- `GET /v1/artifacts/{artifact_id}/content`

### RAG administration and query
- `POST /v1/rag/sources/reconcile`
- `POST /v1/rag/query`

### Internal worker callbacks
- `POST /internal/jobs/{job_id}/started`
- `POST /internal/jobs/{job_id}/retrying`
- `POST /internal/jobs/{job_id}/complete`

## Typical workflow

1. Create a session.
2. Send a message to enqueue a design job.
3. Poll the job endpoint until the worker reports a terminal state.
4. Fetch logs and artifacts for the session.
5. Retrieve a presigned URL for the desired artifact.

## Notes

- The worker uses the internal job routes to update state transitions.
- The API persists model execution metadata such as `MODEL_ID`, `MODEL_BACKEND`, and `MODEL_DEVICE`.
- Current health checks include the API itself and an LLM readiness probe.
