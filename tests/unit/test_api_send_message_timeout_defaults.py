from fastapi.testclient import TestClient

from app.main import app
from app.db import Base, engine


def setup_module(module):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def teardown_module(module):
    Base.metadata.drop_all(bind=engine)


def test_send_message_with_content_only_payload_does_not_raise_unboundlocal(monkeypatch):
    client = TestClient(app)

    monkeypatch.setattr("app.routes.sessions.ensure_llm_ready", lambda: None)

    created = client.post("/v1/sessions", json={"title": "t"})
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    response = client.post(f"/v1/sessions/{session_id}/messages", json={"content": "hi"})

    assert response.status_code == 202
    body = response.json()
    assert body["session_id"] == session_id
    assert body["job_id"]
    assert body["user_message_id"]
