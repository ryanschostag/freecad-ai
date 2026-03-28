import importlib.util
import sys
from pathlib import Path


def _load_jobs_module():
    repo_root = Path(__file__).resolve().parents[2]
    worker_root = repo_root / "services" / "freecad-worker"
    if str(worker_root) not in sys.path:
        sys.path.insert(0, str(worker_root))
    module_path = worker_root / "worker" / "jobs.py"
    spec = importlib.util.spec_from_file_location("worker_jobs_no_token_alias_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_run_repair_loop_job_does_not_accept_llm_max_tokens_alias_anymore():
    jobs = _load_jobs_module()
    assert 'llm_max_tokens' not in jobs.run_repair_loop_job.__code__.co_varnames
    assert 'max_tokens' not in jobs.run_repair_loop_job.__code__.co_varnames
