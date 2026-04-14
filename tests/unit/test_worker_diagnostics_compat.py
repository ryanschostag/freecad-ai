import importlib.util
import sys
from pathlib import Path


def _load_jobs_module():
    repo_root = Path(__file__).resolve().parents[2]
    worker_root = repo_root / "services" / "freecad-worker"
    if str(worker_root) not in sys.path:
        sys.path.insert(0, str(worker_root))
    module_path = worker_root / "worker" / "jobs.py"
    spec = importlib.util.spec_from_file_location("worker_jobs_diagnostics_compat_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[assignment]
    return module


def test_invalid_python_diagnostics_keep_backward_compatible_summary_fields(monkeypatch):
    jobs = _load_jobs_module()
    uploads = []

    monkeypatch.setattr(jobs, "chat", lambda *_args, **_kwargs: "result = (")
    monkeypatch.setattr(jobs, "_resolve_freecadcmd", lambda: "/usr/bin/freecadcmd")
    monkeypatch.setattr(
        jobs,
        "put_object",
        lambda key, data, content_type="application/octet-stream": uploads.append(
            {"key": key, "data": data, "content_type": content_type}
        ),
    )

    result = jobs.run_repair_loop_job(
        job_id="job-1",
        session_id="session-1",
        user_message_id="message-1",
        prompt="create a simple box",
        export={"fcstd": True, "step": True, "stl": False},
        max_repair_iterations=2,
    )

    assert result["passed"] is False
    diag_upload = next(u for u in uploads if u["key"].endswith(".diagnostics.json"))
    assert b'"generation_attempts": 2' in diag_upload["data"]
    assert b'"generation_attempt_details": [' in diag_upload["data"]
    assert b'"model_export_skipped_reason": "generated macro is not valid Python"' in diag_upload["data"]
