import importlib.util
import sys
from pathlib import Path



def _load_jobs_module():
    repo_root = Path(__file__).resolve().parents[2]
    worker_root = repo_root / "services" / "freecad-worker"
    if str(worker_root) not in sys.path:
        sys.path.insert(0, str(worker_root))
    module_path = worker_root / "worker" / "jobs.py"
    spec = importlib.util.spec_from_file_location("worker_jobs_model_artifacts_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[assignment]
    return module



def test_run_repair_loop_job_uploads_generated_models_to_models_prefix(monkeypatch):
    jobs = _load_jobs_module()

    uploads = []

    monkeypatch.setattr(
        jobs,
        "chat",
        lambda *_args, **_kwargs: "import FreeCAD as App\nApp.newDocument('Model')\n",
    )
    monkeypatch.setattr(jobs, "_resolve_freecadcmd", lambda: "/usr/bin/freecadcmd")
    monkeypatch.setattr(
        jobs,
        "put_object",
        lambda key, data, content_type="application/octet-stream": uploads.append(
            {"key": key, "data": data, "content_type": content_type}
        ),
    )

    def fake_run_freecad_headless(*, freecadcmd, macro_path, outdir, export, timeout_seconds):
        out = Path(outdir)
        assert freecadcmd == "/usr/bin/freecadcmd"
        assert Path(macro_path).read_text(encoding="utf-8").startswith("import FreeCAD")
        assert export == {"fcstd": True, "step": True, "stl": False}
        (out / "model.FCStd").write_bytes(b"fcstd-bytes")
        (out / "model.step").write_bytes(b"step-bytes")
        return "ok", "", 0

    monkeypatch.setattr(jobs, "_run_freecad_headless", fake_run_freecad_headless)

    result = jobs.run_repair_loop_job(
        job_id="job-1",
        session_id="session-1",
        user_message_id="message-1",
        prompt="create a simple box 10 mm x 20 mm x 5 mm",
        export={"fcstd": True, "step": True, "stl": False},
    )

    artifact_kinds = [a["kind"] for a in result["artifacts"]]
    assert "freecad_macro_py" in artifact_kinds
    assert "freecad_model_fcstd" in artifact_kinds
    assert "cad_model_step" in artifact_kinds
    assert "cad_model_stl" not in artifact_kinds

    upload_keys = [u["key"] for u in uploads]
    assert "sessions/session-1/macros/message-1.gen0.py" in upload_keys
    assert "sessions/session-1/models/message-1.FCStd" in upload_keys
    assert "sessions/session-1/models/message-1.step" in upload_keys
    assert all("/macros/" in key or "/models/" in key or "/diagnostics/" in key for key in upload_keys)
    assert result["passed"] is True



def test_run_repair_loop_job_skips_model_export_when_macro_is_not_valid_python(monkeypatch):
    jobs = _load_jobs_module()

    uploads = []

    monkeypatch.setattr(
        jobs,
        "chat",
        lambda *_args, **_kwargs: "# Fake LLM Response\n\nThis is not valid Python",
    )
    monkeypatch.setattr(jobs, "_resolve_freecadcmd", lambda: "/usr/bin/freecadcmd")
    monkeypatch.setattr(
        jobs,
        "put_object",
        lambda key, data, content_type="application/octet-stream": uploads.append(
            {"key": key, "data": data, "content_type": content_type}
        ),
    )

    called = {"value": False}

    def fake_run_freecad_headless(**_kwargs):
        called["value"] = True
        raise AssertionError("FreeCAD should not be invoked for invalid Python")

    monkeypatch.setattr(jobs, "_run_freecad_headless", fake_run_freecad_headless)

    result = jobs.run_repair_loop_job(
        job_id="job-1",
        session_id="session-1",
        user_message_id="message-1",
        prompt="create a simple box 10 mm x 20 mm x 5 mm",
        export={"fcstd": True, "step": True, "stl": False},
    )

    assert called["value"] is False
    assert [a["kind"] for a in result["artifacts"]] == [
        "freecad_macro_py",
        "job_diagnostics_json",
    ]
    diag_upload = next(u for u in uploads if u["key"].endswith(".diagnostics.json"))
    assert b'"model_export_skipped_reason": "generated macro is not valid Python; skipped model export"' in diag_upload["data"]
    assert result["passed"] is True
