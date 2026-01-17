# FreeCAD AI

## Environment Configuration Updates

### Profiles
This project supports two main Docker Compose profiles:

- **test**: Uses a fake LLM service for fast, deterministic pytest runs.
- **cpu**: Uses a real local GGUF-based LLM via llama.cpp.

Switch profiles with a single command:

```bash
docker compose --profile test up -d
docker compose --profile cpu up -d
```

### Test Dependencies

Before running tests locally, install test-only dependencies:

```bash
pip install -r tests/requirements.txt
```

### Environment Variables

Key variables:

- `CAD_AGENT_BASE_URL`
  - Test profile default: `http://localhost:8081`
  - CPU profile default: `http://localhost:8080`
  - Automatically set via `pytest.ini` when running pytest.

- `LLM_BASE_URL`
  - CPU profile: `http://llm:8000`
  - Test profile: `http://llm-fake:8000`

### MinIO Credentials

Default MinIO credentials **must be changed**.

Update in `.env` or environment:

```env
MINIO_ROOT_USER=your_user
MINIO_ROOT_PASSWORD=your_password
```

These are consumed automatically by the MinIO service.

### Testing Guarantee

The test profile mirrors CPU behavior by:
- Identical API and worker images
- Same queue, job state transitions, and artifact handling
- Only the LLM backend differs

A passing pytest run is required before CPU deployment.
