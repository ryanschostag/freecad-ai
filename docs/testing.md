# Testing

This project runs API and integration tests inside Docker (the `test` profile). The tests depend on Docker-only services (Postgres, Redis, workers, fake LLM, MinIO), so running pytest directly on the host is intentionally unsupported.

## Start the test profile

From the repository root:

```bash
docker compose --profile test up -d --build
```

This starts:
- api-test (FastAPI service)
- freecad-worker-test (RQ worker)
- db (Postgres + pgvector)
- redis
- llm-fake
- minio + minio-init

## Run tests (recommended): test-runner container

The `test-runner` service runs pytest inside the Docker network and installs test dependencies from `tests/requirements.txt`.

Run:

```bash
docker compose --profile test run --rm test-runner
```

This is the recommended approach for CI/CD because it is self-contained and produces clean stdout/stderr for logs.

## Run tests (alternative): exec into api-test

If you prefer to run pytest interactively inside the API container:

```bash
docker compose --profile test exec api-test sh
```

Then inside the container:

```bash
pip install -r /repo/tests/requirements.txt
pytest -vv --full-trace
```

Notes:
- The `test-runner` approach is preferred because it guarantees pytest and dependencies are present.
- The API container image may not include pytest by default, depending on build configuration.

## Tear down

```bash
docker compose --profile test down
```

## Troubleshooting

- If a test cannot reach `redis`, `db`, or `llm-fake`, ensure you are running pytest inside Docker (via `test-runner` or `exec`), not on the host.
- If MinIO bucket creation fails, check `minio` and `minio-init` container logs:
  ```bash
  docker compose logs minio minio-init
  ```
