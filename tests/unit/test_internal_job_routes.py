from pathlib import Path


def test_internal_job_routes_are_not_double_prefixed():
    repo_root = Path(__file__).resolve().parents[2]
    main_py = (repo_root / "services" / "api" / "app" / "main.py").read_text(encoding="utf-8")
    internal_py = (repo_root / "services" / "api" / "app" / "routes" / "internal_jobs.py").read_text(encoding="utf-8")

    assert 'app.include_router(internal_jobs.router, prefix="/internal")' in main_py
    assert '@router.post("/jobs/{job_id}/started")' in internal_py
    assert '@router.post("/jobs/{job_id}/complete")' in internal_py
    assert '@router.post("/jobs/{job_id}/retrying")' in internal_py
    assert '/internal/jobs/{job_id}/started' not in internal_py
    assert '/internal/internal/jobs/{job_id}/started' not in main_py
