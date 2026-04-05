import importlib.util
from pathlib import Path


def _load_jobs_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "services" / "freecad-worker" / "worker" / "jobs.py"
    import sys
    worker_root = str(module_path.parent.parent)
    if worker_root not in sys.path:
        sys.path.insert(0, worker_root)
    spec = importlib.util.spec_from_file_location("worker_jobs_runner_recovery", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_runner_script_recovers_from_macro_export_api_errors():
    jobs = _load_jobs_module()
    runner = jobs._runner_script()
    assert 'VALIDATION:EXEC_EXCEPTION:' in runner
    assert 'status["exception"] = traceback.format_exc()' in runner
    assert 'shape_items = _collect_export_objects(g)' in runner
