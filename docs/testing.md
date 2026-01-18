# Testing

This project runs API and integration tests **inside Docker**, not on the host machine.

The test suite depends on Docker-only services such as Postgres, Redis, background workers, and a fake LLM service. Because Docker service hostnames (for example `redis` or `llm-fake`) do not resolve from the host, running pytest locally on the host is intentionally unsupported.

All tests are executed inside the Docker test profile to ensure deterministic, production-like behavior.

---

## Test Profiles

The repository defines a dedicated Docker profile for testing.

- `default`
  Used for local development and manual testing.

- `test`
  Used for automated testing. Installs pytest and test dependencies, starts all required services, and runs the API in async mode.

---

## Running Tests Locally

### Step 1: Build and start the test profile

From the repository root:

```bash
docker compose --profile test up -d --build
```

This will:
- Build the API container with pytest and test dependencies installed
- Start Postgres, Redis, workers, and the fake LLM service
- Start the API service in async mode

---

### Step 2: Run pytest inside the API container

```bash
docker compose --profile test exec api-test pytest -vv --full-trace
```

Pytest runs inside the Docker network, so all service hostnames resolve correctly and async job execution behaves the same as in production.

---

### Step 3: Tear down (optional)

```bash
docker compose --profile test down
```

---

## Test Dependencies

Test-only Python dependencies are defined in:

```
tests/requirements.txt
```

These dependencies are installed **only** when building the API image under the `test` profile. Production images do not include pytest or test tooling.

---

## Test Types

### API / Integration Tests

Location:

```
services/api/app/tests/
```

Characteristics:
- Run inside Docker
- Use real HTTP requests
- Depend on Postgres, Redis, workers, and the fake LLM
- Validate async job creation, execution, and API responses

These are the default tests executed when running pytest in the test profile.

---

## CI Usage

CI should run tests the same way as local development:

```bash
docker compose --profile test up -d --build
docker compose --profile test exec api-test pytest -vv
```

This ensures consistency between local and CI environments.

---

## Important Notes

Do not run pytest on the host machine:

```bash
pytest
```

Host-based pytest will fail due to missing Docker services and unresolved DNS names.

Always run pytest inside the Docker test profile.
