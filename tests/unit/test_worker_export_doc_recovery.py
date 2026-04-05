import importlib.util
import sys
from pathlib import Path


def _load_jobs_module():
    repo_root = Path(__file__).resolve().parents[2]
    worker_root = repo_root / "services" / "freecad-worker"
    if str(worker_root) not in sys.path:
        sys.path.insert(0, str(worker_root))
    module_path = worker_root / "worker" / "jobs.py"
    spec = importlib.util.spec_from_file_location("worker_jobs_export_doc_recovery_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[assignment]
    return module


def test_runner_script_builds_dedicated_export_document_and_checks_outputs():
    jobs = _load_jobs_module()
    script = jobs._runner_script()

    assert "def _build_export_document" in script
    assert 'App.newDocument("ExportModel")' in script
    assert "_collect_shapes_from_documents" in script
    assert "_collect_shapes_from_globals" in script
    assert "VALIDATION:NO_EXPORTABLE_SHAPES" in script
    assert "VALIDATION:EXPORT_FAILED:FCSTD:missing_output" in script
    assert "VALIDATION:EXPORT_FAILED:STEP:missing_output" in script
