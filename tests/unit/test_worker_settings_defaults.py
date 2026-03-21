from pathlib import Path
import importlib.util
import sys


def _load_worker_settings_module():
    repo_root = Path(__file__).resolve().parents[2]
    worker_root = repo_root / "services" / "freecad-worker"
    if str(worker_root) not in sys.path:
        sys.path.insert(0, str(worker_root))
    module_path = worker_root / "worker" / "settings.py"
    spec = importlib.util.spec_from_file_location("worker_settings_defaults_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_worker_settings_default_llm_base_url_matches_compose_runtime_alias(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    settings_module = _load_worker_settings_module()

    assert settings_module.Settings().llm_base_url == "http://freecad-ai-llm:8000"
