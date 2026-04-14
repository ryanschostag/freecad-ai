import importlib.util
import sys
from pathlib import Path


def _load_jobs_module():
    repo_root = Path(__file__).resolve().parents[2]
    worker_root = repo_root / "services" / "freecad-worker"
    if str(worker_root) not in sys.path:
        sys.path.insert(0, str(worker_root))
    module_path = worker_root / "worker" / "jobs.py"
    spec = importlib.util.spec_from_file_location("worker_jobs_runner_ui_compat_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[assignment]
    return module


def test_runner_script_bootstraps_model_document_for_ui_style_macros():
    jobs = _load_jobs_module()
    script = jobs._runner_script()
    assert 'App.getDocument("Model")' in script
    assert 'App.newDocument("Model")' in script
    assert 'g["doc"] = model_doc' in script


def test_runner_failure_prompt_includes_traceback_context():
    jobs = _load_jobs_module()
    prompt = jobs._repair_prompt_for_runner_failure(
        "import FreeCAD as App",
        failure="FreeCAD completed but did not produce any model artifacts",
        stdout="stdout text",
        stderr="stderr text",
        runner_status={"exception": "Traceback... NameError: handle_width", "reason": "no_exportable_shapes"},
    )
    assert "Traceback... NameError: handle_width" in prompt
    assert "no_exportable_shapes" in prompt
    assert "FreeCAD 1.0.x" in prompt
