import os, time, requests, pytest

BASE_URL = os.environ.get("CAD_AGENT_BASE_URL", "http://localhost:8080")

@pytest.mark.integration
def test_e2e_session_job():
    # The e2e test is designed to run against the docker **test profile**
    # (fake LLM + worker + redis + postgres). When running inside the api-test
    # container, the API is typically reachable at http://localhost:8080.

    # Skip when API isn't reachable (eg: running outside docker)
    try:
        hr = requests.get(f"{BASE_URL}/v1/health", timeout=2.0)
        if hr.status_code != 200:
            pytest.skip(f"API not healthy at {BASE_URL} (status={hr.status_code})")
    except Exception:
        pytest.skip(f"API not reachable at {BASE_URL}; run inside docker test profile")

    # Create session
    r = requests.post(f"{BASE_URL}/v1/sessions", json={"title":"itest"})
    assert r.status_code == 201
    sid = r.json()["session_id"]

    # Enqueue message
    r = requests.post(f"{BASE_URL}/v1/sessions/{sid}/messages", json={
        "content":"Create a simple box 10mm x 20mm x 5mm",
        "mode":"design",
        "export":{"fcstd":True,"step":True,"stl":False},
        "units":"mm",
        "tolerance_mm":0.1
    })
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    # Poll until finished/failed
    for _ in range(180):
        jr = requests.get(f"{BASE_URL}/v1/jobs/{job_id}")
        assert jr.status_code == 200
        st = jr.json()["status"]
        if st in ("finished","failed"):
            break
        time.sleep(1.0)
    assert st == "finished", jr.json()

    # List artifacts
    ar = requests.get(f"{BASE_URL}/v1/sessions/{sid}/artifacts")
    assert ar.status_code == 200
    artifacts = ar.json()["artifacts"]
    assert len(artifacts) >= 1
