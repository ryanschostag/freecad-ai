import importlib.util
import json
import sys
from pathlib import Path


def _load_jobs_module():
    repo_root = Path(__file__).resolve().parents[2]
    worker_root = repo_root / "services" / "freecad-worker"
    if str(worker_root) not in sys.path:
        sys.path.insert(0, str(worker_root))
    module_path = worker_root / "worker" / "jobs.py"
    spec = importlib.util.spec_from_file_location("worker_jobs_retry_training_state_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[assignment]
    return module


def test_run_repair_loop_job_persists_retry_training_state_to_configured_directory(monkeypatch, tmp_path):
    jobs = _load_jobs_module()

    responses = iter([
        "import FreeCAD\nresult = (",
        "import FreeCAD as App\ndoc = App.ActiveDocument\nif doc is None:\n    doc = App.newDocument('Model')\ndoc.recompute()\n",
    ])

    monkeypatch.setattr(jobs, "chat", lambda *_args, **_kwargs: next(responses))
    monkeypatch.setattr(jobs, "_resolve_freecadcmd", lambda: None)
    monkeypatch.setattr(jobs, "put_object", lambda *args, **kwargs: None)
    monkeypatch.setattr(jobs, "_mark_job_started", lambda **kwargs: None)
    monkeypatch.setattr(jobs, "_mark_job_retrying", lambda **kwargs: None)
    monkeypatch.setattr(jobs, "_mark_job_complete", lambda **kwargs: None)
    jobs.settings.llm_state_dir = str(tmp_path)

    result = jobs.run_repair_loop_job(
        job_id="job-1",
        session_id="session-1",
        user_message_id="message-1",
        prompt="create separate razor handle housing blade spacers and screw",
        export={"fcstd": False, "step": False, "stl": False},
        max_repair_iterations=2,
    )

    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert result["passed"] is True
    assert latest["run_id"] == "session-session-1-job-1-iter-1"
    assert (tmp_path / latest["run_id"] / "inference_profile.json").exists()
    assert result["artifacts"][0]["kind"] == "freecad_macro_py"
