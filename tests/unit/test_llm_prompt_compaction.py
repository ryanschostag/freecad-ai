import importlib.util
import sys
from pathlib import Path


def _load_module(name: str, relative_path: str):
    repo_root = Path(__file__).resolve().parents[2]
    worker_root = repo_root / "services" / "freecad-worker"
    if str(worker_root) not in sys.path:
        sys.path.insert(0, str(worker_root))
    module_path = worker_root / relative_path
    spec = importlib.util.spec_from_file_location(name, module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[assignment]
    return module


def test_compact_retry_prompt_keeps_request_bounded():
    prompts = _load_module("worker_prompts_compact_test", "worker/prompts.py")

    prompt = "A" * 6000
    issue = "(" * 10 + " was never closed at line 55"
    messages = prompts.build_compact_retry_prompt(prompt, issue, "mm", 0.1)

    assert len(messages) == 2
    assert "...<snip>..." in messages[1]["content"]
    assert len(messages[1]["content"]) < 4000


def test_jobs_detects_probable_truncation_from_syntax_error():
    jobs = _load_module("worker_jobs_compact_test", "worker/jobs.py")

    assert jobs._is_probably_truncated_syntax_issue("'(' was never closed at line 55") is True
    assert jobs._is_probably_truncated_syntax_issue("invalid syntax at line 2") is False
