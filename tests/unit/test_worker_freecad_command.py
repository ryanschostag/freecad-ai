import importlib.util
import sys
from pathlib import Path


def _load_jobs_module():
    repo_root = Path(__file__).resolve().parents[2]
    worker_root = repo_root / "services" / "freecad-worker"
    if str(worker_root) not in sys.path:
        sys.path.insert(0, str(worker_root))
    module_path = worker_root / "worker" / "jobs.py"
    spec = importlib.util.spec_from_file_location("worker_jobs_freecad_cmd_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[assignment]
    return module


def test_run_freecad_headless_executes_runner_script_file(monkeypatch):
    jobs = _load_jobs_module()

    seen = {}

    class Result:
        stdout = "ok"
        stderr = ""
        returncode = 0

    def fake_run(cmd, capture_output, text, timeout, env):
        seen["cmd"] = cmd
        seen["capture_output"] = capture_output
        seen["text"] = text
        seen["timeout"] = timeout
        seen["env"] = env
        runner_path = Path(cmd[1])
        assert runner_path.name == "runner.py"
        assert runner_path.read_text(encoding="utf-8")
        return Result()

    monkeypatch.setattr(jobs.subprocess, "run", fake_run)

    stdout, stderr, returncode = jobs._run_freecad_headless(
        freecadcmd="/usr/bin/freecadcmd",
        macro_path="/tmp/input.py",
        outdir="/tmp/outdir",
        export={"fcstd": True, "step": True, "stl": False},
        timeout_seconds=321,
    )

    assert seen["cmd"][0] == "/usr/bin/freecadcmd"
    assert seen["cmd"][1].endswith("runner.py")
    assert "-c" not in seen["cmd"]
    assert seen["capture_output"] is True
    assert seen["text"] is True
    assert seen["timeout"] == 321
    assert seen["env"]["CAD_MACRO_PATH"] == "/tmp/input.py"
    assert stdout == "ok"
    assert stderr == ""
    assert returncode == 0


def test_run_repair_loop_job_keeps_last_generated_macro_when_retry_llm_call_fails(monkeypatch):
    jobs = _load_jobs_module()

    uploads = []
    responses = iter([
        "import FreeCAD as App\nApp.newDocument('Model')\nbox = 1\n",
        RuntimeError("timed out"),
    ])

    def fake_chat(_messages, **_kwargs):
        item = next(responses)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(jobs, "chat", fake_chat)
    monkeypatch.setattr(jobs, "_resolve_freecadcmd", lambda: "/usr/bin/freecadcmd")
    monkeypatch.setattr(
        jobs,
        "put_object",
        lambda key, data, content_type="application/octet-stream": uploads.append(
            {"key": key, "data": data, "content_type": content_type}
        ),
    )

    monkeypatch.setattr(jobs, "_run_freecad_headless", lambda **_kwargs: ("", "", 0))

    result = jobs.run_repair_loop_job(
        job_id="job-1",
        session_id="session-1",
        user_message_id="message-1",
        prompt="create something",
        export={"fcstd": True, "step": False, "stl": False},
        max_repair_iterations=2,
    )

    assert result["passed"] is False
    macro_upload = next(u for u in uploads if u["key"].endswith(".gen0.py"))
    assert b"App.newDocument('Model')" in macro_upload["data"]
    assert b"Generated macro was empty" not in macro_upload["data"]
