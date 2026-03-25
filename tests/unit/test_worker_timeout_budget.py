import importlib.util
import sys
from pathlib import Path


def _load_jobs_module():
    repo_root = Path(__file__).resolve().parents[2]
    worker_root = repo_root / "services" / "freecad-worker"
    if str(worker_root) not in sys.path:
        sys.path.insert(0, str(worker_root))
    module_path = worker_root / "worker" / "jobs.py"
    spec = importlib.util.spec_from_file_location("worker_jobs_budget_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[assignment]
    return module


def test_llm_generation_budget_stays_within_job_timeout():
    jobs = _load_jobs_module()

    budget = jobs._llm_generation_budget(900)

    assert budget["max_attempts"] == 1
    assert budget["max_tokens"] == 1200
    assert 30 <= budget["timeout_s"] < 900


def test_llm_generation_budget_scales_up_for_long_jobs():
    jobs = _load_jobs_module()

    budget = jobs._llm_generation_budget(12000)

    assert budget["max_attempts"] == 1
    assert budget["max_tokens"] == 2400
    assert 30 <= budget["timeout_s"] < 12000


def test_run_repair_loop_job_uses_bounded_llm_budget(monkeypatch):
    jobs = _load_jobs_module()

    uploads = []
    seen = {}

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
    )

    assert result["passed"] is True
    assert seen["max_attempts"] == 1
    assert seen["max_tokens"] == 1200
    assert seen["timeout_s"] < 900
    assert seen["stop"] == ["<|im_end|>", "</s>", "<|endoftext|>"]
    assert uploads
