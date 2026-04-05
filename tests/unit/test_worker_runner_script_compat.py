import importlib.util
import sys
from pathlib import Path


def _load_jobs_module():
    repo_root = Path(__file__).resolve().parents[2]
    worker_root = repo_root / "services" / "freecad-worker"
    if str(worker_root) not in sys.path:
        sys.path.insert(0, str(worker_root))
    module_path = worker_root / "worker" / "jobs.py"
    spec = importlib.util.spec_from_file_location("worker_jobs_runner_script_compat_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[assignment]
    return module


def test_runner_script_preserves_legacy_and_export_doc_contracts():
    jobs = _load_jobs_module()
    script = jobs._runner_script()
    assert "except SystemExit as e:" in script
    assert 'doc.saveAs(base + ".FCStd")' in script
    assert 'App.listDocuments().values()' in script
    assert 'Recovered_' in script
    assert '_collect_export_objects' in script
    assert 'App.newDocument("ExportModel")' in script
