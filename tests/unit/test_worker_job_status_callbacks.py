import importlib.util
import sys
from pathlib import Path


def _load_jobs_module():
    repo_root = Path(__file__).resolve().parents[2]
    worker_root = repo_root / "services" / "freecad-worker"
    if str(worker_root) not in sys.path:
        sys.path.insert(0, str(worker_root))
    module_path = worker_root / "worker" / "jobs.py"
    spec = importlib.util.spec_from_file_location("worker_jobs_status_callbacks_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[assignment]
    return module


def test_run_repair_loop_job_notifies_api_started_and_complete(monkeypatch):
    jobs = _load_jobs_module()
    notifications = []
    uploads = []

    monkeypatch.setattr(jobs, "_mark_job_started", lambda **kw: notifications.append(("started", kw)))
    monkeypatch.setattr(jobs, "_mark_job_complete", lambda **kw: notifications.append(("complete", kw)))
    monkeypatch.setattr(jobs, "chat", lambda *a, **k: "import FreeCAD as App\nApp.newDocument('Model')\n")
    monkeypatch.setattr(jobs, "_resolve_freecadcmd", lambda: None)
    monkeypatch.setattr(jobs, "put_object", lambda key, data, content_type=None: uploads.append((key, data, content_type)))

    result = jobs.run_repair_loop_job(
        job_id="job-1",
        session_id="session-1",
        user_message_id="msg-1",
        prompt="make a cube",
        timeout_seconds=120,
    )

    assert result["passed"] is True
    assert [name for name, _ in notifications] == ["started", "complete"]
    assert notifications[0][1]["job_id"] == "job-1"
    assert notifications[1][1]["job_id"] == "job-1"
    assert notifications[1][1]["passed"] is True
    assert notifications[1][1]["result"]["job_id"] == "job-1"
    assert any(key.endswith("/macros/msg-1.gen0.py") for key, _, _ in uploads)


def test_run_repair_loop_job_reports_failed_completion(monkeypatch):
    jobs = _load_jobs_module()
    notifications = []
    uploads = []

    monkeypatch.setattr(jobs, "_mark_job_started", lambda **kw: notifications.append(("started", kw)))
    monkeypatch.setattr(jobs, "_mark_job_complete", lambda **kw: notifications.append(("complete", kw)))
    monkeypatch.setattr(jobs, "chat", lambda *a, **k: "def broken(\n")
    monkeypatch.setattr(jobs, "_resolve_freecadcmd", lambda: None)
    monkeypatch.setattr(jobs, "put_object", lambda key, data, content_type=None: uploads.append((key, data, content_type)))

    result = jobs.run_repair_loop_job(
        job_id="job-2",
        session_id="session-2",
        user_message_id="msg-2",
        prompt="make a broken thing",
        timeout_seconds=120,
        max_repair_iterations=1,
    )

    assert result["passed"] is False
    assert [name for name, _ in notifications] == ["started", "complete"]
    complete = notifications[1][1]
    assert complete["passed"] is False
    assert "issues" in complete["error"]
    assert any(key.endswith("/diagnostics/msg-2.diagnostics.json") for key, _, _ in uploads)
