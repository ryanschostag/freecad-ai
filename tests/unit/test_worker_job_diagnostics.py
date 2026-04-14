import importlib.util
import sys
from pathlib import Path


def _load_jobs_module():
    repo_root = Path(__file__).resolve().parents[2]
    worker_root = repo_root / "services" / "freecad-worker"
    if str(worker_root) not in sys.path:
        sys.path.insert(0, str(worker_root))
    module_path = worker_root / "worker" / "jobs.py"
    spec = importlib.util.spec_from_file_location("worker_jobs_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[assignment]
    return module


def test_empty_llm_output_produces_diagnostic_artifacts(monkeypatch):
    jobs = _load_jobs_module()

    uploads = []

    monkeypatch.setattr(jobs, "chat", lambda *_args, **_kwargs: "   ")
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
        mode="design",
        export={"fcstd": True, "step": True, "stl": False},
        units="mm",
        tolerance_mm=0.1,
    )

    assert result["passed"] is False
    assert result["issues"] == ["llm returned an empty response"]
    assert [a["kind"] for a in result["artifacts"]] == [
        "freecad_macro_py",
        "job_diagnostics_json",
        "job_reason_txt",
    ]

    macro_upload = uploads[0]
    assert b"Generated macro was empty" in macro_upload["data"]

    diag_upload = uploads[1]
    assert b'"placeholder_used": true' in diag_upload["data"]
    assert b'llm returned an empty response' in diag_upload["data"]

    reason_upload = uploads[2]
    assert reason_upload["content_type"] == "text/plain"
    assert reason_upload["data"] == b"llm returned an empty response\n"
