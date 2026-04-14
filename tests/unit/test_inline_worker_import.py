from pathlib import Path


def test_sessions_route_uses_lazy_worker_import_helper():
    content = Path("services/api/app/routes/sessions.py").read_text()
    assert "def _load_run_repair_loop_job" in content
    assert "from worker.jobs import run_repair_loop_job" in content
    assert "sys.path.insert(0, worker_root_str)" in content
    assert "run_repair_loop_job = _load_run_repair_loop_job()" in content
