from fastapi import FastAPI
from app.routes import health, sessions, logs, artifacts, rag, jobs
from app.routes import internal_jobs
from app.db import init_db
app = FastAPI(title="CAD Agent API", version="1.1.0")


@app.on_event("startup")
def _startup_init_db() -> None:
    # Ensure required tables/extensions exist for dev/test runs.
    init_db()


app.include_router(health.router, prefix="/v1")
app.include_router(sessions.router, prefix="/v1")
app.include_router(logs.router, prefix="/v1")
app.include_router(artifacts.router, prefix="/v1")
app.include_router(rag.router, prefix="/v1")

app.include_router(jobs.router, prefix="/v1")

# Internal (worker-to-api) callbacks.
app.include_router(internal_jobs.router, prefix="/internal")
