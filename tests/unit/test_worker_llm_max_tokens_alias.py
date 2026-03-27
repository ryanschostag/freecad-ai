import importlib.util
import sys
from pathlib import Path


def _load_jobs_module():
    repo_root = Path(__file__).resolve().parents[2]
    worker_root = repo_root / "services" / "freecad-worker"
    if str(worker_root) not in sys.path:
        sys.path.insert(0, str(worker_root))
    module_path = worker_root / "worker" / "jobs.py"
    spec = importlib.util.spec_from_file_location("worker_jobs_llm_max_tokens_alias_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[assignment]
    return module


def test_run_repair_loop_job_accepts_llm_max_tokens_alias(monkeypatch):
    jobs = _load_jobs_module()

    seen = {}
    uploads = []

    def fake_chat(messages, **kwargs):
        seen.update(kwargs)
        return "import FreeCAD as App\nApp.newDocument('Model')\n"

    monkeypatch.setattr(jobs, "chat", fake_chat)
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
        prompt="create a simple box 10 mm x 20 mm x 5 mm",
        timeout_seconds=900,
        llm_max_tokens=256,
    )

    assert result["passed"] is True
    assert seen["max_tokens"] == 256
    assert uploads
