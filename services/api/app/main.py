from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.routes import artifacts, health, internal_jobs, jobs, logs, rag, sessions

# NOTE: Keep startup resilient. Tests import `app.main` during collection.
# If `app.db` changes between branches (or is mid-refactor), importing a missing
# symbol here will break collection entirely.
import app.db as db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan.

    FastAPI's `@app.on_event` startup hooks are deprecated; use lifespan.
    Keep this resilient so pytest collection doesn't fail if db.init_db is
    absent during refactors.
    """

    init = getattr(db, "init_db", None)
    if callable(init):
        init()
    yield


app = FastAPI(title="CAD Agent API", version="1.1.0", lifespan=lifespan)


app.include_router(health.router, prefix="/v1")
app.include_router(sessions.router, prefix="/v1")
app.include_router(logs.router, prefix="/v1")
app.include_router(artifacts.router, prefix="/v1")
app.include_router(rag.router, prefix="/v1")

app.include_router(jobs.router, prefix="/v1")

# Internal (worker-to-api) callbacks.
app.include_router(internal_jobs.router, prefix="/internal")
