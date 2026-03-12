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


def test_run_repair_loop_job_collects_nondefault_model_filenames(monkeypatch):
    jobs = _load_jobs_module()

    uploads = []

    monkeypatch.setattr(jobs, "chat", lambda *_args, **_kwargs: "import FreeCAD as App\nApp.newDocument('Model')\n")
    monkeypatch.setattr(jobs, "_detect_freecadcmd", lambda: "/usr/bin/freecadcmd")

    def fake_run_freecad_headless(_freecadcmd, _macro_path, outdir, export, _timeout_seconds):
        outdir_path = Path(outdir)
        (outdir_path / "RazorBladeHousing.FCStd").write_bytes(b"fcstd-custom-name")
        (outdir_path / "RazorBladeHousing.step").write_bytes(b"step-custom-name")
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
        job_id="job-custom",
        session_id="session-custom",
        user_message_id="message-custom",
        prompt="create a custom named part",
        export={"fcstd": True, "step": True, "stl": False},
    )

    assert result["passed"] is True
    assert result["issues"] == []
    assert uploads[1]["key"] == "sessions/session-custom/models/message-custom.FCStd"
    assert uploads[1]["data"] == b"fcstd-custom-name"
    assert uploads[2]["key"] == "sessions/session-custom/models/message-custom.step"
    assert uploads[2]["data"] == b"step-custom-name"


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


def test_run_freecad_headless_executes_runner_script_without_console_flag(monkeypatch):
    jobs = _load_jobs_module()

    called = {}

    class CompletedProcess:
        stdout = "RUNNER:START\nRUNNER:DONE\n"
        stderr = ""
        returncode = 0

    def fake_run(cmd, capture_output, text, timeout, env, input=None):
        called["cmd"] = cmd
        called["capture_output"] = capture_output
        called["text"] = text
        called["timeout"] = timeout
        called["env"] = env
        return CompletedProcess()

    monkeypatch.setattr(jobs.subprocess, "run", fake_run)

    stdout, stderr, returncode = jobs._run_freecad_headless(
        "/usr/bin/freecadcmd",
        "/tmp/macro.py",
        "/tmp/outdir",
        {"fcstd": True, "step": True, "stl": False},
        123,
    )

    assert called["cmd"][0] == "/usr/bin/freecadcmd"
    assert called["cmd"][1].endswith("runner.py")
    assert called["cmd"] == [called["cmd"][0], called["cmd"][1]]
    assert called["capture_output"] is True
    assert called["text"] is True
    assert called["timeout"] == 123
    assert called["env"]["CAD_MACRO_PATH"] == "/tmp/macro.py"
    assert called["env"]["CAD_OUTDIR"] == "/tmp/outdir"
    assert called["env"]["CAD_EXPORT_FCSTD"] == "1"
    assert called["env"]["CAD_EXPORT_STEP"] == "1"
    assert called["env"]["CAD_EXPORT_STL"] == "0"
    assert (stdout, stderr, returncode) == ("RUNNER:START\nRUNNER:DONE\n", "", 0)



def test_run_repair_loop_job_rejects_syntax_invalid_macro(monkeypatch):
    jobs = _load_jobs_module()

    uploads = []

    monkeypatch.setattr(jobs, "chat", lambda *_args, **_kwargs: "import FreeCAD\nfoo = (")
    monkeypatch.setattr(jobs, "_detect_freecadcmd", lambda: "/usr/bin/freecadcmd")
    monkeypatch.setattr(
        jobs,
        "put_object",
        lambda key, data, content_type="application/octet-stream": uploads.append(
            {"key": key, "data": data, "content_type": content_type}
        ),
    )

    result = jobs.run_repair_loop_job(
        job_id="job-syntax",
        session_id="session-syntax",
        user_message_id="message-syntax",
        prompt="broken macro",
    )

    assert result["passed"] is False
    assert result["issues"] == [
        "generated macro failed syntax check: SyntaxError: '(' was never closed (line 2)"
    ]
    assert [a["kind"] for a in result["artifacts"]] == [
        "freecad_macro_py",
        "job_diagnostics_json",
        "job_reason_txt",
    ]
    assert b'Generated macro was empty; writing a safe placeholder.' in uploads[0]["data"]
    assert b'generated macro failed syntax check' in uploads[1]["data"]
    assert b"runner_markers_seen" in uploads[1]["data"]


def test_run_freecad_headless_falls_back_to_console_stdin_when_script_argument_is_ignored(monkeypatch):
    jobs = _load_jobs_module()

    calls = []

    class CompletedProcess:
        def __init__(self, stdout, stderr, returncode):
            self.stdout = stdout
            self.stderr = stderr
            self.returncode = returncode

    def fake_run(cmd, capture_output, text, timeout, env, input=None):
        calls.append({
            "cmd": cmd,
            "capture_output": capture_output,
            "text": text,
            "timeout": timeout,
            "env": env,
            "input": input,
        })
        if len(calls) == 1:
            return CompletedProcess("FreeCAD banner", "", 0)
        return CompletedProcess("RUNNER:START\nRUNNER:DONE\n", "", 0)

    monkeypatch.setattr(jobs.subprocess, "run", fake_run)

    stdout, stderr, returncode = jobs._run_freecad_headless(
        "/usr/bin/freecadcmd",
        "/tmp/macro.py",
        "/tmp/outdir",
        {"fcstd": True, "step": True, "stl": False},
        123,
    )

    assert calls[0]["cmd"][0] == "/usr/bin/freecadcmd"
    assert calls[0]["cmd"][1].endswith("runner.py")
    assert calls[0]["input"] is None
    assert calls[1]["cmd"] == ["/usr/bin/freecadcmd", "-c"]
    assert "RUNNER:START" in calls[1]["input"]
    assert calls[1]["env"]["CAD_MACRO_PATH"] == "/tmp/macro.py"
    assert (stdout, stderr, returncode) == ("RUNNER:START\nRUNNER:DONE\n", "", 0)
