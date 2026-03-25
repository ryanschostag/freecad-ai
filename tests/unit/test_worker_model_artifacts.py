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



def test_run_repair_loop_job_retries_invalid_python_and_uploads_models(monkeypatch):
    jobs = _load_jobs_module()

    uploads = []
    prompts = []
    responses = iter(
        [
            "import FreeCAD\nresult = (",
            "import FreeCAD as App\nApp.newDocument('Model')\n",
        ]
    )

    def fake_chat(messages, **_kwargs):
        prompts.append(messages[-1]["content"])
        return next(responses)

    monkeypatch.setattr(jobs, "chat", fake_chat)
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
        assert Path(macro_path).read_text(encoding="utf-8") == "import FreeCAD as App\nApp.newDocument('Model')"
        (out / "model.FCStd").write_bytes(b"fcstd-bytes")
        return "ok", "", 0

    monkeypatch.setattr(jobs, "_run_freecad_headless", fake_run_freecad_headless)

    result = jobs.run_repair_loop_job(
        job_id="job-1",
        session_id="session-1",
        user_message_id="message-1",
        prompt="create a simple box 10 mm x 20 mm x 5 mm",
        export={"fcstd": True, "step": False, "stl": False},
        max_repair_iterations=3,
    )

    assert result["passed"] is True
    assert result["iterations"] == 2
    assert len(prompts) == 2
    assert "not valid Python" in prompts[1]
    upload_keys = [u["key"] for u in uploads]
    assert "sessions/session-1/models/message-1.FCStd" in upload_keys

    diag_upload = next(u for u in uploads if u["key"].endswith(".diagnostics.json"))
    assert b'"status": "invalid_python"' in diag_upload["data"]
    assert b'"successful_iteration": 2' in diag_upload["data"]



def test_run_repair_loop_job_fails_after_invalid_python_exhausts_retries(monkeypatch):
    jobs = _load_jobs_module()

    uploads = []

    monkeypatch.setattr(
        jobs,
        "chat",
        lambda *_args, **_kwargs: "# Fake LLM Response\nresult = (",
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
        max_repair_iterations=2,
    )

    assert called["value"] is False
    assert result["passed"] is False
    assert result["iterations"] == 2
    assert "generated macro is not valid Python after 2 attempt(s)" in result["issues"][0]
    assert [a["kind"] for a in result["artifacts"]] == [
        "freecad_macro_py",
        "job_diagnostics_json",
    ]
    diag_upload = next(u for u in uploads if u["key"].endswith(".diagnostics.json"))
    assert b'"model_export_skipped_reason": "generated macro is not valid Python"' in diag_upload["data"]


def test_run_repair_loop_job_normalizes_truncated_markdown_fence_before_validation(monkeypatch):
    jobs = _load_jobs_module()

    uploads = []

    monkeypatch.setattr(
        jobs,
        "chat",
        lambda *_args, **_kwargs: "```python\nimport FreeCAD as App\nApp.newDocument('Model')\n",
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
        assert Path(macro_path).read_text(encoding="utf-8") == "import FreeCAD as App\nApp.newDocument('Model')"
        (out / "model.FCStd").write_bytes(b"fcstd-bytes")
        return "ok", "", 0

    monkeypatch.setattr(jobs, "_run_freecad_headless", fake_run_freecad_headless)

    result = jobs.run_repair_loop_job(
        job_id="job-1",
        session_id="session-1",
        user_message_id="message-1",
        prompt="create a simple box 10 mm x 20 mm x 5 mm",
        export={"fcstd": True, "step": False, "stl": False},
        max_repair_iterations=1,
    )

    assert result["passed"] is True
    assert result["iterations"] == 1
    diag_upload = next(u for u in uploads if u["key"].endswith(".diagnostics.json"))
    assert b'"raw_macro_chars": 50' not in diag_upload["data"]
    assert b'"status": "exported_models"' in diag_upload["data"]
