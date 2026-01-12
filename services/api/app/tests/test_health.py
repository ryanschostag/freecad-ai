from fastapi.testclient import TestClient
from app.main import app

def test_health():
    c = TestClient(app)
    r = c.get("/v1/health")
    assert r.status_code == 200
