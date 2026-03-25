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

    budget = jobs._llm_generation_budget(900, prompt_tokens=200)

    assert budget["max_attempts"] == 1
    assert budget["max_tokens"] > 0
    assert budget["ctx_size"] == 4096
    assert budget["requested_max_tokens"] is None
    assert budget["cap_reason"] == "context_window"
    assert 30 <= budget["timeout_s"] < 900


def test_run_repair_loop_job_uses_context_aware_llm_budget(monkeypatch):
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
    assert seen["max_tokens"] > 0
    assert seen["timeout_s"] < 900
    assert seen["stop"] == ["<|im_end|>", "</s>", "<|endoftext|>"]
    assert uploads


def test_llm_generation_budget_caps_requested_max_tokens_to_context_window():
    jobs = _load_jobs_module()

    budget = jobs._llm_generation_budget(900, 36000, prompt_tokens=1500, ctx_size=4096)

    assert budget["requested_max_tokens"] == 36000
    assert budget["available_completion_tokens"] == 2340
    assert budget["max_tokens"] == 2340
    assert budget["cap_reason"] == "context_window"


def test_llm_generation_budget_uses_context_window_when_request_is_unbounded():
    jobs = _load_jobs_module()

    budget = jobs._llm_generation_budget(900, None, prompt_tokens=1500, ctx_size=4096)

    assert budget["requested_max_tokens"] is None
    assert budget["max_tokens"] == budget["available_completion_tokens"]
    assert budget["cap_reason"] == "context_window"
