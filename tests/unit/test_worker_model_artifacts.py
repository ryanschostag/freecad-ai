import importlib.util
import sys
from pathlib import Path


def _load_jobs_module():
    repo_root = Path(__file__).resolve().parents[2]
    worker_root = repo_root / "services" / "freecad-worker"
    if str(worker_root) not in sys.path:
        sys.path.insert(0, str(worker_root))
    module_path = worker_root / "worker" / "jobs.py"
    spec = importlib.util.spec_from_file_location("worker_jobs_model_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[assignment]
    return module


def test_run_repair_loop_job_uploads_rendered_models(monkeypatch):
    jobs = _load_jobs_module()

    uploads = []

    monkeypatch.setattr(jobs, "chat", lambda *_args, **_kwargs: "import FreeCAD as App\nApp.newDocument('Model')\n")
    monkeypatch.setattr(jobs, "_detect_freecadcmd", lambda: "/usr/bin/freecadcmd")

    def fake_run_freecad_headless(_freecadcmd, _macro_path, outdir, export, _timeout_seconds):
        assert export == {"fcstd": True, "step": True, "stl": False}
        outdir_path = Path(outdir)
        (outdir_path / "model.FCStd").write_bytes(b"fcstd-bytes")
        (outdir_path / "model.step").write_bytes(b"step-bytes")
        return "ok", "", 0

    monkeypatch.setattr(jobs, "_run_freecad_headless", fake_run_freecad_headless)
    monkeypatch.setattr(
        jobs,
        "put_object",
        lambda key, data, content_type="application/octet-stream": uploads.append(
            {"key": key, "data": data, "content_type": content_type}
        ),
    )

    result = jobs.run_repair_loop_job(
        job_id="job-1",
        session_id="session-1",
        user_message_id="message-1",
        prompt="create a simple box 10 mm x 20 mm x 5 mm",
        export={"fcstd": True, "step": True, "stl": False},
    )

    assert result["passed"] is True
    assert result["issues"] == []
    assert [a["kind"] for a in result["artifacts"]] == [
        "freecad_macro_py",
        "freecad_model_fcstd",
        "freecad_model_step",
        "job_diagnostics_json",
    ]
    assert uploads[1]["key"] == "sessions/session-1/models/message-1.FCStd"
    assert uploads[1]["data"] == b"fcstd-bytes"
    assert uploads[2]["key"] == "sessions/session-1/models/message-1.step"
    assert uploads[2]["content_type"] == "model/step"
    assert b'"uploaded_model_kinds": [' in uploads[3]["data"]
    assert b'"freecad_model_fcstd"' in uploads[3]["data"]
    assert b'"freecad_model_step"' in uploads[3]["data"]


def test_run_repair_loop_job_records_missing_freecad_binary(monkeypatch):
    jobs = _load_jobs_module()

    uploads = []

    monkeypatch.setattr(jobs, "chat", lambda *_args, **_kwargs: "import FreeCAD as App\nApp.newDocument('Model')\n")
    monkeypatch.setattr(jobs, "_detect_freecadcmd", lambda: None)
    monkeypatch.setattr(
        jobs,
        "put_object",
        lambda key, data, content_type="application/octet-stream": uploads.append(
            {"key": key, "data": data, "content_type": content_type}
        ),
    )

    result = jobs.run_repair_loop_job(
        job_id="job-2",
        session_id="session-2",
        user_message_id="message-2",
        prompt="create a simple cylinder",
    )

    assert result["passed"] is True
    assert result["issues"] == ["freecadcmd not found; skipping model export"]
    assert [a["kind"] for a in result["artifacts"]] == [
        "freecad_macro_py",
        "job_diagnostics_json",
    ]
    assert b'"freecadcmd": null' in uploads[1]["data"]
    assert b'"executed": false' in uploads[1]["data"]

