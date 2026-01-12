from fastapi import FastAPI
from app.routes import health, sessions, logs, artifacts, rag

app = FastAPI(title="CAD Agent API", version="1.0.0")

app.include_router(health.router, prefix="/v1", tags=["health"])
app.include_router(sessions.router, prefix="/v1", tags=["sessions"])
app.include_router(logs.router, prefix="/v1", tags=["logs"])
app.include_router(artifacts.router, prefix="/v1", tags=["artifacts"])
app.include_router(rag.router, prefix="/v1", tags=["rag"])
