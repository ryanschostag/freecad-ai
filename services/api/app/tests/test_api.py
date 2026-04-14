from fastapi.testclient import TestClient
from app.main import app
import time

client = TestClient(app)

def test_health():
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

def test_session_flow():
    r = client.post("/v1/sessions", json={"title":"t"})
    assert r.status_code == 201
    sid = r.json()["session_id"]

    r2 = client.post(f"/v1/sessions/{sid}/messages", json={"content":"hi"})
    # Message ingestion enqueues an async job and returns 202 + job_id.
    assert r2.status_code == 202
    body = r2.json()
    assert body["session_id"] == sid
    job_id = body["job_id"]

    # Poll job status until finished (or fail fast if job fails).
    result = None
    for _ in range(1200):  # ~40s at 0.2s sleep
        jr = client.get(f"/v1/jobs/{job_id}")
        assert jr.status_code == 200
        j = jr.json()
        if j["status"] == "finished":
            result = j.get("result") or {}
            break
        if j["status"] == "failed":
            raise AssertionError(f"job failed: {j.get('error')}")
        time.sleep(0.2)

    assert result is not None, "job did not finish in time"
    artifacts = result.get("artifacts") or []
    assert len(artifacts) >= 1
    assert any(a.get("kind") == "freecad_macro_py" for a in artifacts)

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
