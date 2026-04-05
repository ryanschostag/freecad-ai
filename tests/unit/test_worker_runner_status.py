import importlib.util
import sys
from pathlib import Path


def _load_jobs_module():
    repo_root = Path(__file__).resolve().parents[2]
    worker_root = repo_root / "services" / "freecad-worker"
    if str(worker_root) not in sys.path:
        sys.path.insert(0, str(worker_root))
    module_path = worker_root / "worker" / "jobs.py"
    spec = importlib.util.spec_from_file_location("worker_jobs_runner_status_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[assignment]
    return module


def test_runner_script_executes_without_main_guard_and_writes_status_file():
    jobs = _load_jobs_module()
    script = jobs._runner_script()
    assert 'runner_status.json' in script
    assert '"runner_invoked": True' in script
    assert 'if __name__ == "__main__":' not in script
    assert '\ntry:\n    main()\nexcept Exception:' in script
