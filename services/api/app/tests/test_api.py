"""API integration tests.

These tests are intended to run *inside* the docker "test" profile, where the
API has network access to Postgres/Redis/worker/llm-fake.

Run:
  docker compose --profile test up -d
  docker compose --profile test exec api-test pytest -vv --full-trace
"""

from __future__ import annotations

import os
import time

import pytest
import requests


BASE_URL = os.environ.get("CAD_AGENT_BASE_URL") or os.environ.get("API_BASE_URL") or "http://localhost:8080"
BASE_URL = BASE_URL.rstrip("/")


def _wait_for_api() -> None:
    """Skip tests when API isn't reachable (eg: running outside docker)."""
    try:
        r = requests.get(f"{BASE_URL}/v1/health", timeout=2.0)
        if r.status_code != 200:
            pytest.skip(f"API not healthy at {BASE_URL} (status={r.status_code})")
    except Exception:
        pytest.skip(f"API not reachable at {BASE_URL}; run tests inside docker test profile")


def test_health():
    _wait_for_api()
    r = requests.get(f"{BASE_URL}/v1/health", timeout=5.0)
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


@pytest.mark.integration
def test_session_flow():
    _wait_for_api()

    # Create session
    r = requests.post(f"{BASE_URL}/v1/sessions", json={"title": "t"}, timeout=10.0)
    assert r.status_code == 201
    sid = r.json()["session_id"]

    # Enqueue message (async)
    r2 = requests.post(
        f"{BASE_URL}/v1/sessions/{sid}/messages",
        json={"content": "hi"},
        timeout=20.0,
    )
    assert r2.status_code in (200, 202)
    job_id = r2.json()["job_id"]

    # Poll job until finished/failed
    status = None
    last = None
    for _ in range(180):
        jr = requests.get(f"{BASE_URL}/v1/jobs/{job_id}", timeout=10.0)
        assert jr.status_code == 200
        last = jr.json()
        status = last.get("status")
        if status in ("finished", "failed"):
            break
        time.sleep(1.0)
    assert status == "finished", last

    # Artifacts should be listed for the session
    ar = requests.get(f"{BASE_URL}/v1/sessions/{sid}/artifacts", timeout=10.0)
    assert ar.status_code == 200
    artifacts = ar.json().get("artifacts") or []
    assert len(artifacts) >= 1

    # Metrics should reflect at least one prompt/completion
    r3 = requests.get(f"{BASE_URL}/v1/sessions/{sid}/metrics", timeout=10.0)
    assert r3.status_code == 200
    m = r3.json()
    assert m.get("prompts", 0) >= 1
    assert m.get("completions", 0) >= 1

    # End session then ensure messages are rejected
    r4 = requests.post(f"{BASE_URL}/v1/sessions/{sid}/end", timeout=10.0)
    assert r4.status_code == 200
    assert r4.json().get("status") == "closed"

    r5 = requests.post(f"{BASE_URL}/v1/sessions/{sid}/messages", json={"content": "should fail"}, timeout=10.0)
    assert r5.status_code == 409


@pytest.mark.integration
def test_fork():
    _wait_for_api()
    r = requests.post(f"{BASE_URL}/v1/sessions", json={"title": "base"}, timeout=10.0)
    assert r.status_code == 201
    sid = r.json()["session_id"]

    r2 = requests.post(f"{BASE_URL}/v1/sessions/{sid}/fork", timeout=10.0)
    assert r2.status_code == 201
    child = r2.json()
    assert child["parent_session_id"] == sid
