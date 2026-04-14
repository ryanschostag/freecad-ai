import importlib.util
import json
from pathlib import Path


def _load_module(name: str, relative_path: str):
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / relative_path
    import sys
    worker_root = str(repo_root / "services" / "freecad-worker")
    if worker_root not in sys.path:
        sys.path.insert(0, worker_root)
    spec = importlib.util.spec_from_file_location(name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_build_session_training_snapshot_captures_known_failure_lessons(tmp_path):
    module = _load_module("worker_session_training", "services/freecad-worker/worker/session_training.py")
    snapshot = module.build_session_training_snapshot(
        session_id="session-1",
        previous_job_id="job-1",
        previous_prompt="create a box",
        previous_macro_text='if doc.isExportable("BaseBox"):\n    doc.export([], "x.step")',
        diagnostics_text=json.dumps({"error": "AttributeError: 'App.Document' object has no attribute 'isExportable'"}),
        issues=["FreeCAD completed but did not produce any model artifacts; runner exception: AttributeError: 'App.Document' object has no attribute 'isExportable'"],
        state_dir=str(tmp_path),
    )
    assert snapshot.run_id == "session-session-1-job-1"
    assert snapshot.inference_profile is not None
    rendered = json.dumps(snapshot.inference_profile)
    assert "Do not call doc.isExportable" in rendered
    assert "Do not call doc.export" in rendered


def test_iteration_training_snapshot_captures_ui_macro_failures_and_writes_latest(tmp_path):
    module = _load_module("worker_session_training_iter", "services/freecad-worker/worker/session_training.py")
    import importlib
    model_state = importlib.import_module("worker.model_state")
    snapshot = module.persist_iteration_training_snapshot(
        session_id="session-1",
        job_id="job-99",
        iteration=2,
        previous_prompt="create a razor with separated parts",
        previous_macro_text="doc = FreeCAD.getDocument('Model')\nhandle_spacer = Part.makeBox(handle_width, handle_length, handle_height, handle_spacer_center, handle_spacer_axis)",
        diagnostics_text=(
            "<class 'NameError'>: Unknown document 'Model'\n"
            "<class 'NameError'>: name 'handle_width' is not defined\n"
            "<class 'TypeError'>: argument 3 must be Base.Vector, not tuple"
        ),
        issues=["ui macro execution failed"],
        state_dir=str(tmp_path),
    )
    latest = model_state.read_latest_pointer(str(tmp_path))
    rendered = json.dumps(snapshot.inference_profile)
    assert latest is not None
    assert latest["run_id"] == snapshot.run_id
    assert latest["manifest_path"].startswith(f"sqlite://{tmp_path / 'llm-state.sqlite3'}#run_id={snapshot.run_id}")
    assert (tmp_path / "llm-state.sqlite3").exists()
    assert snapshot.run_id == "session-session-1-job-99-iter-2"
    assert "Never call App.getDocument('Model') unless that document already exists" in rendered
    assert "Do not reference undefined variables" in rendered
    assert "pass FreeCAD.Vector instances instead of Python tuples" in rendered
