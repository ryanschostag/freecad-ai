import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health():
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

@pytest.mark.integration
def test_session_flow():
    r = client.post("/v1/sessions", json={"title":"t"})
    assert r.status_code == 201
    sid = r.json()["session_id"]

    r2 = client.post(f"/v1/sessions/{sid}/messages", json={"content":"hi"})
    assert r2.status_code == 200
    body = r2.json()
    assert body["session_id"] == sid
    assert body["assistant_message"]["role"] == "assistant"
    assert len(body["artifacts"]) >= 1

    r3 = client.get(f"/v1/sessions/{sid}/metrics")
    assert r3.status_code == 200
    m = r3.json()
    assert m["prompts"] >= 1
    assert m["completions"] >= 1

    r4 = client.post(f"/v1/sessions/{sid}/end")
    assert r4.status_code == 200
    assert r4.json()["status"] == "closed"

    r5 = client.post(f"/v1/sessions/{sid}/messages", json={"content":"should fail"})
    assert r5.status_code in (409,)

def test_fork():
    r = client.post("/v1/sessions", json={"title":"base"})
    sid = r.json()["session_id"]
    r2 = client.post(f"/v1/sessions/{sid}/fork")
    assert r2.status_code == 201
    child = r2.json()
    assert child["parent_session_id"] == sid
