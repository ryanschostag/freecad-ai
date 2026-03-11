# FreeCAD AI

## Environment Configuration Updates

### Profiles
This project supports multiple Docker Compose profiles:

- **test**: Uses a fake LLM service for fast, deterministic pytest runs inside Docker.
- **cpu**: Uses a real local GGUF-based LLM via llama.cpp.
- **gpu** (optional): Uses llama.cpp with GPU acceleration via an override file.

Switch profiles with:

```bash
docker compose --profile test up -d
docker compose --profile cpu up -d
```

---

## Environment Variables

Key variables used across profiles:

- `CAD_AGENT_BASE_URL`
  - Test profile default: `http://localhost:8081`
  - CPU profile default: `http://localhost:8080`

- `LLM_BASE_URL`
  - CPU profile: `http://llm:8000`
  - Test profile: `http://llm-fake:8000`

- `MODEL_ID`, `MODEL_BACKEND`, `MODEL_DEVICE`
  - Set by Docker Compose per profile so the API can persist accurate execution metadata.
  - CPU profile defaults: `cpu-default` / `llama.cpp` / `cpu`
  - Test profile defaults: `test-default` / `fake-llm` / `cpu`
  - GPU profile defaults: `gpu-default` / `llama.cpp` / `gpu`

---

## Object Storage (MinIO)

Artifacts (macros, validation reports, exports) are stored in S3-compatible object storage.

- Local / dev uses **MinIO**
- Default console: http://localhost:9001
- Credentials are defined in `.env`:

```env
MINIO_ROOT_USER=your_user
MINIO_ROOT_PASSWORD=your_password
```

---

## API Documentation (Swagger / OpenAPI)

The API is implemented using FastAPI and automatically exposes OpenAPI documentation.

### Swagger UI (interactive)
Use this for exploration and external integration:

- **http://localhost:8080/docs**

This allows you to:
- Browse all endpoints (`/v1/sessions`, `/v1/jobs`, `/v1/artifacts`, etc.)
- Inspect request/response schemas
- Execute API calls directly from the browser

### ReDoc
A ReDoc endpoint is also configured but may appear blank depending on browser and FastAPI/ReDoc version:

- http://localhost:8080/redoc

If `/redoc` renders a white page, use `/docs` instead — it is the canonical, fully supported UI.

### Raw OpenAPI spec
For client generation or external tooling:

- http://localhost:8080/openapi.json

---

## Testing

All tests are intended to run **inside Docker** using the `test` profile.

See **`docs/testing.md`** for:
- Test-runner usage
- CI integration
- Dependency handling
- Warning management

---

## Documentation Guide (`docs/`)

The `docs/` directory contains focused, task-oriented documentation:

- **`docs/testing.md`**  
  Canonical guide for running pytest inside Docker, including the test-runner container and CI usage.

- **`docs/architecture.drawio`**  
  Editable system architecture diagram (open with draw.io / diagrams.net).  
  Shows API, worker, Redis, Postgres, LLM, and object storage interactions.

- **`docs/design.md`** *(if present)*  
  High-level architectural decisions and design rationale.

- **`docs/development.md`** *(if present)*  
  Local development notes, debugging tips, and contributor guidance.

Each document is intended to stay narrowly scoped so the README can remain a high-level entry point.

---

## CAD Agent CLI

The command-line client lives in:

- `tools/cad_agent/`

See **`tools/cad_agent/README.md`** for:
- Full CLI usage
- Explanation of all options (`--export`, `--tolerance-mm`, etc.)
- Meaning of JSON output
- Artifact download workflows

---

## Notes

- The `/health` endpoint is available both at `/health` and `/v1/health` for CLI compatibility.
- Authentication is currently disabled; future auth mechanisms will automatically appear in Swagger.
