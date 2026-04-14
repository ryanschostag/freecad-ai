from fastapi import FastAPI

from app.routes import artifacts, health, internal_jobs, jobs, logs, rag, sessions

# NOTE: Keep startup resilient. Tests import `app.main` during collection.
# If `app.db` changes between branches (or is mid-refactor), importing a missing
# symbol here will break collection entirely.
import app.db as db


app = FastAPI(title="CAD Agent API", version="1.1.0")


@app.on_event("startup")
def _startup_init_db() -> None:
    # Ensure required tables/extensions exist for dev/test runs.
    # `db.init_db` is idempotent; if it doesn't exist, fall back to no-op.
    init = getattr(db, "init_db", None)
    if callable(init):
        init()


app.include_router(health.router, prefix="/v1")
app.include_router(health.router)
app.include_router(sessions.router, prefix="/v1")
app.include_router(logs.router, prefix="/v1")
app.include_router(artifacts.router, prefix="/v1")
app.include_router(rag.router, prefix="/v1")

app.include_router(jobs.router, prefix="/v1")

# Internal (worker-to-api) callbacks.
app.include_router(internal_jobs.router, prefix="/internal")
