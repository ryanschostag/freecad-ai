FROM python:3.11-slim

WORKDIR /app

# When building from the repo root (used by the docker "test" profile), the
# API sources live under services/api.
COPY services/api/pyproject.toml /app/pyproject.toml
COPY services/api/alembic.ini /app/alembic.ini
COPY services/api/alembic /app/alembic
COPY services/api/app /app/app

# Include the worker + shared packages so the API can enqueue jobs using a real callable.
# This avoids RQ import-attribute edge cases from string-based func references.
COPY services/freecad-worker/worker /app/worker
COPY services/freecad-worker/shared /app/shared

RUN pip install --no-cache-dir -U pip && \
    pip install --no-cache-dir -e .

# Optional: install test dependencies when building the "test" profile.
ARG INSTALL_TEST_DEPS=0
COPY tests/requirements.txt /app/tests/requirements.txt
RUN if [ "$INSTALL_TEST_DEPS" = "1" ]; then \
      pip install --no-cache-dir -r /app/tests/requirements.txt; \
    fi

# Copy repo-level tests and tools so they can be executed inside the container.
COPY tests /app/tests
COPY tools /app/tools

EXPOSE 8080
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8080"]
