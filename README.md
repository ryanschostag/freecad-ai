# FreeCAD AI

## Environment Configuration Updates

### Profiles
This project supports two main Docker Compose profiles:

- **test**: Uses a fake LLM service for fast, deterministic pytest runs inside Docker.
- **cpu**: Uses a real local GGUF-based LLM via llama.cpp.

Switch profiles with:

```bash
docker compose --profile test up -d
docker compose --profile cpu up -d
```

### Environment Variables

Key variables:

- `CAD_AGENT_BASE_URL`
  - Test profile default: `http://localhost:8081` (host access)
  - CPU profile default: `http://localhost:8080`

- `LLM_BASE_URL`
  - CPU profile: `http://llm:8000`
  - Test profile: `http://llm-fake:8000`

### MinIO Credentials

Default MinIO credentials should be changed.

Update in `.env` or environment:

```env
MINIO_ROOT_USER=your_user
MINIO_ROOT_PASSWORD=your_password
```

These are consumed automatically by the MinIO service.

## Testing

All tests are intended to run inside Docker using the `test` profile.

See `docs/testing.md` for the canonical testing workflow, including how to run tests via the `test-runner` container in local development and CI.
