from fastapi import FastAPI
from app.routes import health, sessions, logs, artifacts, rag, jobs
app = FastAPI(title="CAD Agent API", version="1.1.0")
app.include_router(health.router, prefix="/v1")
app.include_router(sessions.router, prefix="/v1")
app.include_router(logs.router, prefix="/v1")
app.include_router(artifacts.router, prefix="/v1")
app.include_router(rag.router, prefix="/v1")

app.include_router(jobs.router, prefix="/v1")
