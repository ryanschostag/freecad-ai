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
        return "ok\nRUNNER:START\nRUNNER:DONE\n", "", 0

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
        return "RUNNER:START\nRUNNER:DONE\n", "", 0

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


def test_runner_markers_seen_requires_exact_marker_lines():
    jobs = _load_jobs_module()

    stdout = "[FreeCAD Console mode]\nRUNNER:START\n"
    stderr = '>>> print("RUNNER:DONE")\nIndentationError: unexpected indent\n'

    assert jobs._runner_markers_seen(stdout, stderr) is False
    start_seen, done_seen = jobs._runner_markers(stdout, stderr)
    assert start_seen is True
    assert done_seen is False


def test_build_generation_messages_parses_embedded_chat_template():
    jobs = _load_jobs_module()

    prompt = (
        "<|im_start|>system\nSystem instructions\n<|im_end|>\n"
        "<|im_start|>user\nBuild a box\n<|im_end|>\n"
        "<|im_start|>assistant\n"
    )

    messages = jobs._build_generation_messages(prompt, "design", "mm", 0.1)

    assert messages == [
        {"role": "system", "content": "System instructions"},
        {"role": "user", "content": "Build a box"},
    ]


def test_run_freecad_headless_executes_runner_script_without_console_flag(monkeypatch):
    jobs = _load_jobs_module()

    called = {}

    class CompletedProcess:
        stdout = "RUNNER:START\nRUNNER:DONE\n"
        stderr = ""
        returncode = 0

    def fake_run(cmd, input=None, capture_output=None, text=None, timeout=None, env=None):
        called["cmd"] = cmd
        called["input"] = input
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
    assert called["input"] is None
    assert called["capture_output"] is True
    assert called["text"] is True
    assert called["timeout"] == 123
    assert called["env"]["CAD_MACRO_PATH"] == "/tmp/macro.py"
    assert called["env"]["CAD_OUTDIR"] == "/tmp/outdir"
    assert called["env"]["CAD_EXPORT_FCSTD"] == "1"
    assert called["env"]["CAD_EXPORT_STEP"] == "1"
    assert called["env"]["CAD_EXPORT_STL"] == "0"
    assert (stdout, stderr, returncode) == ("RUNNER:START\nRUNNER:DONE\n", "", 0)


def test_run_repair_loop_job_repairs_truncated_syntax_invalid_macro(monkeypatch):
    jobs = _load_jobs_module()

    uploads = []
    chat_calls = []
    responses = iter([
        "import FreeCAD\nfoo = (",
        "import FreeCAD as App\nApp.newDocument('Model')\n",
    ])

    def fake_chat(messages, **_kwargs):
        chat_calls.append(messages)
        return next(responses)

    monkeypatch.setattr(jobs, "chat", fake_chat)
    monkeypatch.setattr(jobs, "_detect_freecadcmd", lambda: "/usr/bin/freecadcmd")

    def fake_run_freecad_headless(_freecadcmd, _macro_path, outdir, _export, _timeout_seconds):
        outdir_path = Path(outdir)
        (outdir_path / "model.FCStd").write_bytes(b"fcstd-bytes")
        (outdir_path / "model.step").write_bytes(b"step-bytes")
        return "RUNNER:START\nRUNNER:DONE\n", "", 0

    monkeypatch.setattr(jobs, "_run_freecad_headless", fake_run_freecad_headless)
    monkeypatch.setattr(
        jobs,
        "put_object",
        lambda key, data, content_type="application/octet-stream": uploads.append(
            {"key": key, "data": data, "content_type": content_type}
        ),
    )

    result = jobs.run_repair_loop_job(
        job_id="job-syntax-repair",
        session_id="session-syntax-repair",
        user_message_id="message-syntax-repair",
        prompt="broken macro",
        max_repair_iterations=2,
    )

    assert result["passed"] is True
    assert result["iterations"] == 2
    assert result["issues"] == [
        "generated macro failed syntax check: SyntaxError: '(' was never closed (line 2); generation may have been truncated"
    ]
    assert len(chat_calls) == 2
    assert "You previously generated this FreeCAD macro" in chat_calls[1][1]["content"]
    assert [a["kind"] for a in result["artifacts"]] == [
        "freecad_macro_py",
        "freecad_model_fcstd",
        "freecad_model_step",
        "job_diagnostics_json",
    ]
    assert uploads[0]["data"].decode("utf-8") == "import FreeCAD as App\nApp.newDocument('Model')\n"
    assert b'"generation_attempts": 2' in uploads[3]["data"]


def test_run_repair_loop_job_still_fails_after_all_repair_attempts(monkeypatch):
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
        max_repair_iterations=2,
    )

    assert result["passed"] is False
    assert result["iterations"] == 2
    assert result["issues"] == [
        "generated macro failed syntax check: SyntaxError: '(' was never closed (line 2); generation may have been truncated",
        "generated macro failed syntax check: SyntaxError: '(' was never closed (line 2); generation may have been truncated",
    ]
    assert [a["kind"] for a in result["artifacts"]] == [
        "freecad_macro_py",
        "job_diagnostics_json",
        "job_reason_txt",
    ]
    assert b'Generated macro was empty; writing a safe placeholder.' in uploads[0]["data"]
    assert b'generated macro failed syntax check' in uploads[1]["data"]
    assert b'"generation_attempts": 2' in uploads[1]["data"]


def test_run_freecad_headless_falls_back_to_console_exec_when_script_argument_is_ignored(monkeypatch):
    jobs = _load_jobs_module()

    calls = []

    class CompletedProcess:
        def __init__(self, stdout, stderr, returncode):
            self.stdout = stdout
            self.stderr = stderr
            self.returncode = returncode

    def fake_run(cmd, input=None, capture_output=None, text=None, timeout=None, env=None):
        calls.append({
            "cmd": cmd,
            "capture_output": capture_output,
            "text": text,
            "timeout": timeout,
            "env": env,
            "input": input,
        })
        if len(calls) == 1:
            return CompletedProcess("FreeCAD banner\nRUNNER:START\n", '>>> print("RUNNER:DONE")\n', 0)
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
    assert "exec(compile(open(" in calls[1]["input"]
    assert "runner.py" in calls[1]["input"]
    assert calls[1]["env"]["CAD_MACRO_PATH"] == "/tmp/macro.py"
    assert (stdout, stderr, returncode) == ("RUNNER:START\nRUNNER:DONE\n", "", 0)


def test_run_repair_loop_job_reports_runner_started_but_not_completed(monkeypatch):
    jobs = _load_jobs_module()

    uploads = []

    monkeypatch.setattr(jobs, "chat", lambda *_args, **_kwargs: "import FreeCAD as App\nApp.newDocument('Model')\n")
    monkeypatch.setattr(jobs, "_detect_freecadcmd", lambda: "/usr/bin/freecadcmd")
    monkeypatch.setattr(jobs, "_run_freecad_headless", lambda *_args, **_kwargs: ("RUNNER:START\n", "", 0))
    monkeypatch.setattr(
        jobs,
        "put_object",
        lambda key, data, content_type="application/octet-stream": uploads.append(
            {"key": key, "data": data, "content_type": content_type}
        ),
    )

    result = jobs.run_repair_loop_job(
        job_id="job-runner",
        session_id="session-runner",
        user_message_id="message-runner",
        prompt="create a simple box",
        export={"fcstd": True, "step": True, "stl": False},
    )

    assert result["passed"] is True
    assert result["issues"] == [
        "freecad runner started but did not complete",
        "freecad execution completed but did not produce any model artifacts",
    ]
    assert b'"runner_start_seen": true' in uploads[1]["data"]
    assert b'"runner_done_seen": false' in uploads[1]["data"]




def test_run_repair_loop_job_repairs_runtime_macro_error_even_when_returncode_is_zero(monkeypatch):
    jobs = _load_jobs_module()

    uploads = []
    chat_calls = []
    responses = iter([
        "import FreeCAD as App\nresult = object()\nresult.Name = \"Result\"\n",
        "import FreeCAD as App\nApp.newDocument(\"Model\")\n",
    ])

    def fake_chat(messages, **_kwargs):
        chat_calls.append(messages)
        return next(responses)

    monkeypatch.setattr(jobs, "chat", fake_chat)
    monkeypatch.setattr(jobs, "_detect_freecadcmd", lambda: "/usr/bin/freecadcmd")

    call_count = {"n": 0}

    def fake_run_freecad_headless(_freecadcmd, _macro_path, outdir, _export, _timeout_seconds):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return (
                "RUNNER:START\n",
                "Traceback...\nAttributeError: 'Part.Compound' object has no attribute 'Name'\n",
                0,
            )
        outdir_path = Path(outdir)
        (outdir_path / "model.FCStd").write_bytes(b"fcstd-bytes")
        (outdir_path / "model.step").write_bytes(b"step-bytes")
        return "RUNNER:START\nRUNNER:DONE\n", "", 0

    monkeypatch.setattr(jobs, "_run_freecad_headless", fake_run_freecad_headless)
    monkeypatch.setattr(
        jobs,
        "put_object",
        lambda key, data, content_type="application/octet-stream": uploads.append(
            {"key": key, "data": data, "content_type": content_type}
        ),
    )

    result = jobs.run_repair_loop_job(
        job_id="job-runtime-repair-zero",
        session_id="session-runtime-repair-zero",
        user_message_id="message-runtime-repair-zero",
        prompt="create a simple box",
        export={"fcstd": True, "step": True, "stl": False},
        max_repair_iterations=2,
    )

    assert result["passed"] is True
    assert result["iterations"] == 2
    assert len(chat_calls) == 2
    assert "Validation issues:" in chat_calls[1][1]["content"]
    assert "runtime_execution_error" in chat_calls[1][1]["content"]
    assert [a["kind"] for a in result["artifacts"]] == [
        "freecad_macro_py",
        "freecad_model_fcstd",
        "freecad_model_step",
        "job_diagnostics_json",
    ]
    assert uploads[1]["key"] == "sessions/session-runtime-repair-zero/models/message-runtime-repair-zero.FCStd"
    assert uploads[2]["key"] == "sessions/session-runtime-repair-zero/models/message-runtime-repair-zero.step"
    assert b'"generation_attempts": 2' in uploads[3]["data"]
def test_run_repair_loop_job_repairs_runtime_macro_error_and_exports_models(monkeypatch):
    jobs = _load_jobs_module()

    uploads = []
    chat_calls = []
    responses = iter([
        "import FreeCAD\nFreeCAD.saveDocument(\"Model.FCStd\")\n",
        "import FreeCAD as App\nApp.newDocument(\"Model\")\n",
    ])

    def fake_chat(messages, **_kwargs):
        chat_calls.append(messages)
        return next(responses)

    monkeypatch.setattr(jobs, "chat", fake_chat)
    monkeypatch.setattr(jobs, "_detect_freecadcmd", lambda: "/usr/bin/freecadcmd")

    call_count = {"n": 0}

    def fake_run_freecad_headless(_freecadcmd, _macro_path, outdir, _export, _timeout_seconds):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return (
                "RUNNER:START\n",
                "Traceback...\nAttributeError: module 'FreeCAD' has no attribute 'saveDocument'\n",
                1,
            )
        outdir_path = Path(outdir)
        (outdir_path / "model.FCStd").write_bytes(b"fcstd-bytes")
        (outdir_path / "model.step").write_bytes(b"step-bytes")
        return "RUNNER:START\nRUNNER:DONE\n", "", 0

    monkeypatch.setattr(jobs, "_run_freecad_headless", fake_run_freecad_headless)
    monkeypatch.setattr(
        jobs,
        "put_object",
        lambda key, data, content_type="application/octet-stream": uploads.append(
            {"key": key, "data": data, "content_type": content_type}
        ),
    )

    result = jobs.run_repair_loop_job(
        job_id="job-runtime-repair",
        session_id="session-runtime-repair",
        user_message_id="message-runtime-repair",
        prompt="create a simple box",
        export={"fcstd": True, "step": True, "stl": False},
        max_repair_iterations=2,
    )

    assert result["passed"] is True
    assert result["iterations"] == 2
    assert result["issues"] == [
        "Do not call FreeCAD.saveDocument/App.saveDocument or perform exports inside the macro. Leave exportable objects in the active document and let the worker export them."
    ]
    assert len(chat_calls) == 2
    assert "Validation issues:" in chat_calls[1][1]["content"]
    assert "forbidden_export_call" in chat_calls[1][1]["content"]
    assert [a["kind"] for a in result["artifacts"]] == [
        "freecad_macro_py",
        "freecad_model_fcstd",
        "freecad_model_step",
        "job_diagnostics_json",
    ]
    assert uploads[1]["key"] == "sessions/session-runtime-repair/models/message-runtime-repair.FCStd"
    assert uploads[2]["key"] == "sessions/session-runtime-repair/models/message-runtime-repair.step"
    assert b'"generation_attempts": 2' in uploads[3]["data"]


def test_run_repair_loop_job_uploads_companion_fcmacro_file(monkeypatch):
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
        job_id="job-fcmacro",
        session_id="session-fcmacro",
        user_message_id="message-fcmacro",
        prompt="create a simple cylinder",
    )

    assert result["passed"] is True
    assert [a["kind"] for a in result["artifacts"]] == [
        "freecad_macro_py",
        "job_diagnostics_json",
    ]
    assert uploads[0]["key"] == "sessions/session-fcmacro/macros/message-fcmacro.gen0.py"
    assert uploads[1]["key"] == "sessions/session-fcmacro/diagnostics/message-fcmacro.diagnostics.json"
    assert uploads[2]["key"] == "sessions/session-fcmacro/macros/message-fcmacro.FCMacro"
    assert uploads[2]["data"] == uploads[0]["data"]


def test_run_repair_loop_job_repairs_null_shape_validation_when_step_export_missing(monkeypatch):
    jobs = _load_jobs_module()

    uploads = []
    chat_calls = []
    responses = iter([
        "import FreeCAD as App\nobj = object()\n",
        'import FreeCAD as App\nApp.newDocument("Model")\n',
    ])

    def fake_chat(messages, **_kwargs):
        chat_calls.append(messages)
        return next(responses)

    monkeypatch.setattr(jobs, "chat", fake_chat)
    monkeypatch.setattr(jobs, "_detect_freecadcmd", lambda: "/usr/bin/freecadcmd")

    call_count = {"n": 0}

    def fake_run_freecad_headless(_freecadcmd, _macro_path, outdir, _export, _timeout_seconds):
        call_count["n"] += 1
        if call_count["n"] == 1:
            outdir_path = Path(outdir)
            (outdir_path / "model.FCStd").write_bytes(b"fcstd-bytes")
            return (
                "RUNNER:START\nRUNNER:DONE\n",
                ">>> <Import> ExportOCAF2.cpp(387): Model1#Result has null shape\n>>> \n",
                0,
            )
        outdir_path = Path(outdir)
        (outdir_path / "model.FCStd").write_bytes(b"fcstd-fixed")
        (outdir_path / "model.step").write_bytes(b"step-fixed")
        return "RUNNER:START\nRUNNER:DONE\n", "", 0

    monkeypatch.setattr(jobs, "_run_freecad_headless", fake_run_freecad_headless)
    monkeypatch.setattr(
        jobs,
        "put_object",
        lambda key, data, content_type="application/octet-stream": uploads.append(
            {"key": key, "data": data, "content_type": content_type}
        ),
    )

    result = jobs.run_repair_loop_job(
        job_id="job-null-shape",
        session_id="session-null-shape",
        user_message_id="message-null-shape",
        prompt="create a simple box",
        export={"fcstd": True, "step": True, "stl": False},
        max_repair_iterations=2,
    )

    assert result["passed"] is True
    assert result["iterations"] == 2
    assert len(chat_calls) == 2
    assert "null_or_nonexportable_shape" in chat_calls[1][1]["content"]
    assert [a["kind"] for a in result["artifacts"]] == [
        "freecad_macro_py",
        "freecad_model_fcstd",
        "freecad_model_step",
        "job_diagnostics_json",
    ]
    assert uploads[2]["key"] == "sessions/session-null-shape/models/message-null-shape.FCStd"
    assert uploads[3]["key"] == "sessions/session-null-shape/models/message-null-shape.step"
    assert uploads[5]["key"] == "sessions/session-null-shape/macros/message-null-shape.FCMacro"
