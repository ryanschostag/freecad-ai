from pathlib import Path


def test_rq_enqueue_uses_enqueue_call_and_passes_job_id_in_kwargs_and_rq_metadata():
    repo_root = Path(__file__).resolve().parents[2]
    sessions_py = (repo_root / "services" / "api" / "app" / "routes" / "sessions.py").read_text(encoding="utf-8")

    assert 'q.enqueue_call(' in sessions_py
    assert 'func="worker.jobs.run_repair_loop_job"' in sessions_py
    assert 'kwargs={' in sessions_py
    assert '"job_id": job_id' in sessions_py
    assert 'job_id=job_id' in sessions_py
    assert 'timeout=rq_timeout_seconds' in sessions_py
    assert 'job_timeout=rq_timeout_seconds' not in sessions_py
