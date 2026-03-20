import importlib.util
import os
import sys
from pathlib import Path


def _load_llm_module():
    repo_root = Path(__file__).resolve().parents[2]
    worker_root = repo_root / "services" / "freecad-worker"
    if str(worker_root) not in sys.path:
        sys.path.insert(0, str(worker_root))
    module_path = worker_root / "worker" / "llm.py"
    spec = importlib.util.spec_from_file_location("worker_llm_candidate_ordering_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_candidate_base_urls_prefers_direct_alias_before_environment_url(monkeypatch):
    llm = _load_llm_module()
    monkeypatch.setenv("LLM_BASE_URL", "http://llm-fake:8000")

    assert llm._candidate_base_urls("http://llm:8000")[:3] == [
        "http://llm:8000",
        "http://freecad-ai-llm:8000",
        "http://llm-fake:8000",
    ]
