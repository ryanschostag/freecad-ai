import importlib.util
import sys
from pathlib import Path


def _load_jobs_module():
    repo_root = Path(__file__).resolve().parents[2]
    worker_root = repo_root / "services" / "freecad-worker"
    if str(worker_root) not in sys.path:
        sys.path.insert(0, str(worker_root))
    module_path = worker_root / "worker" / "jobs.py"
    spec = importlib.util.spec_from_file_location("worker_jobs_prompt_budget_runtime_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_run_repair_loop_job_compacts_oversized_initial_prompt_before_generation(monkeypatch):
    jobs = _load_jobs_module()
    seen_messages = []

    def fake_chat(messages, **kwargs):
        seen_messages.append((messages, kwargs))
        return "import FreeCAD as App\nApp.newDocument('Model')\n"

    monkeypatch.setattr(jobs, "chat", fake_chat)
    monkeypatch.setattr(jobs, "_resolve_freecadcmd", lambda: None)
    monkeypatch.setattr(jobs, "put_object", lambda *a, **k: None)

    huge_prompt = "A" * 20000
    result = jobs.run_repair_loop_job(
        job_id="job-2",
        session_id="session-2",
        user_message_id="msg-2",
        prompt=huge_prompt,
        timeout_seconds=120,
    )

    assert result["passed"] is True
    assert seen_messages
    assert "...<snip>..." in seen_messages[0][0][1]["content"]
    assert "timeout_s" in seen_messages[0][1]
    assert "max_tokens" not in seen_messages[0][1]


def test_short_incomplete_import_is_treated_as_probable_truncation():
    jobs = _load_jobs_module()

    assert jobs._is_probable_truncation("import", "invalid syntax at line 1: import") is True
