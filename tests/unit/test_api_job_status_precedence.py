from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import Base, DimSession, JobRun
from app.routes import jobs as jobs_route


def test_jobs_endpoint_prefers_terminal_db_state_when_redis_unavailable(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    db = TestingSessionLocal()
    now = datetime.now(timezone.utc)
    db.add(DimSession(session_id="session-1", title="test session"))
    db.add(
        JobRun(
            job_id="job-1",
            session_id="session-1",
            user_message_id="msg-1",
            status="finished",
            enqueued_at=now,
            started_at=now,
            finished_at=now,
            result_json={"ok": True},
            error_json={},
        )
    )
    db.commit()
    db.close()

    class FakeRedisJob:
        def get_status(self):
            return "queued"

        @property
        def meta(self):
            return {}

        result = None
        exc_info = None

    monkeypatch.setattr(jobs_route.Job, "fetch", staticmethod(lambda job_id, connection: FakeRedisJob()))

    client = TestClient(app)
    resp = client.get("/v1/jobs/job-1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "finished"
    assert body["result"] == {"ok": True}

    app.dependency_overrides.clear()
