# Docker Profiles and Local Stack

FreeCAD AI is built to run as a composed local stack. Docker Compose profiles let you switch between normal CPU usage, GPU acceleration, and deterministic tests.

## Profiles

### `cpu`
Starts the normal local stack with:
- API
- FreeCAD worker
- Web UI
- Postgres + pgvector
- Redis
- MinIO + bucket init
- llama.cpp server container

Command:

```bash
docker compose --profile cpu up -d --build
```

### `gpu`
Starts the same logical stack but applies the GPU override for the LLM path.

Command:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.override.yml --profile gpu up -d --build
```

### `test`
Starts the Dockerized test environment with:
- `api-test`
- `freecad-worker-test`
- `web-ui-test`
- `llm-fake`
- `test-runner`
- Postgres + pgvector
- Redis
- MinIO

Command:

```bash
docker compose -f docker-compose.yml -f docker-compose.test-override.yml --profile test up -d --build
```

## Persistent mounts

Important mounts include:
- `artifacts_staging` for temporary artifact staging
- `ragconfig` for `rag_sources.yaml`
- `${LLM_STATE_HOST_DIR}:${LLM_STATE_DIR}` for persisted training state

## Important environment variables

- `LLM_BASE_URL`
- `API_BASE_URL`
- `REDIS_URL`
- `DATABASE_URL`
- `MODEL_ID`
- `MODEL_BACKEND`
- `MODEL_DEVICE`
- `LLM_STATE_DIR`
- `LLM_STATE_HOST_DIR`
- `LLM_ERROR_RETRY_LIMIT`
- `S3_ENDPOINT`
- `S3_ACCESS_KEY`
- `S3_SECRET_KEY`

## Recommended lifecycle commands

Start:

```bash
docker compose --profile cpu up -d --build
```

Stop:

```bash
docker compose --profile cpu down
```

Rebuild a changed service:

```bash
docker compose --profile cpu up -d --build api freecad-worker web-ui
```

## Notes

- The test profile uses `CAD_AGENT_INLINE_JOBS=1` so tests can execute predictably without depending on the normal asynchronous queue behavior.
- The `services/rag` directory is not an active runtime service in the current stack.
- The worker and API both mount the same persistent LLM state directory.
