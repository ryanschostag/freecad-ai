# Testing

This project runs API and integration tests **inside Docker** using the `test` profile.
Tests depend on Docker-only services (Postgres, Redis, workers, fake LLM, MinIO), so
running pytest directly on the host is intentionally unsupported.

---

## Required environment configuration (important)

The project root `.env` file defines MinIO credentials:

```
MINIO_ROOT_USER=your_user
MINIO_ROOT_PASSWORD=your_password
```

Because Docker Compose expands environment variables from your shell and `.env`,
it is possible for host-level AWS/S3 variables to override MinIO credentials
and cause test failures (for example: `InvalidAccessKeyId` during artifact upload).

To prevent this, **tests must be run with the provided Docker Compose override file**,
which forces the test containers to use the MinIO credentials defined in `.env`.

---

## Use the test override file (required)

Download the override file:

- docker-compose.test-override.yml

This file ensures that `api-test`, `freecad-worker-test`, and `test-runner`
all use the same MinIO credentials as the MinIO server.

### Download link

You can download the override file here:

sandbox:/mnt/data/docker-compose.test-override.yml

#### Location

This is also found in the project root folder.

---

## Start the test profile

From the repository root, run:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.test-override.yml \
  --profile test up -d --build
```

This starts:
- api-test (FastAPI service)
- freecad-worker-test (RQ worker)
- db (Postgres + pgvector)
- redis
- llm-fake
- minio + minio-init

---

## Run tests (recommended): test-runner container

Run pytest inside Docker using the test-runner service:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.test-override.yml \
  --profile test run --rm test-runner
```

This is the recommended approach for local development and CI/CD.

---

## Tear down

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.test-override.yml \
  --profile test down
```

---

## Troubleshooting

### InvalidAccessKeyId / S3 errors during tests

If you see errors like:

```
InvalidAccessKeyId: The Access Key Id you provided does not exist
```

Ensure that:
- You are using `docker-compose.test-override.yml`
- Your `.env` file defines `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD`
- You are not running pytest on the host

The override file prevents accidental use of host AWS credentials.

---

## Summary

- Tests run only inside Docker
- The `test` profile must be used
- The override file is required to keep MinIO credentials consistent
- `test-runner` is the preferred way to execute pytest
