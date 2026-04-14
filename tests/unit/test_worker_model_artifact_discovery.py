import importlib.util
import sys
from pathlib import Path


def _load_jobs_module():
    repo_root = Path(__file__).resolve().parents[2]
    worker_root = repo_root / "services" / "freecad-worker"
    if str(worker_root) not in sys.path:
        sys.path.insert(0, str(worker_root))
    module_path = worker_root / "worker" / "jobs.py"
    spec = importlib.util.spec_from_file_location("worker_jobs_model_discovery_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[assignment]
    return module


def test_upload_generated_model_artifacts_discovers_macro_named_outputs(monkeypatch, tmp_path):
    jobs = _load_jobs_module()
    uploads = []
    monkeypatch.setattr(
        jobs,
        "put_object",
        lambda key, data, content_type="application/octet-stream": uploads.append(
            {"key": key, "data": data, "content_type": content_type}
        ),
    )

    (tmp_path / "RazorBladeHousing.FCStd").write_bytes(b"fcstd")
    (tmp_path / "RazorBladeHousing.step").write_bytes(b"step")

    artifacts = jobs._upload_generated_model_artifacts(
        outdir=tmp_path,
        session_id="session-1",
        user_message_id="message-1",
    )

    assert [a["kind"] for a in artifacts] == ["freecad_model_fcstd", "cad_model_step"]
    upload_keys = [u["key"] for u in uploads]
    assert "sessions/session-1/models/message-1.FCStd" in upload_keys
    assert "sessions/session-1/models/message-1.step" in upload_keys


def test_runner_script_changes_into_outdir_before_running_macro(monkeypatch, tmp_path):
    jobs = _load_jobs_module()
    runner_code = jobs._runner_script()
    assert 'os.chdir(outdir)' in runner_code
