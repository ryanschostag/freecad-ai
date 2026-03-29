import importlib.util
import sys
from pathlib import Path


def _load_jobs_module():
    repo_root = Path(__file__).resolve().parents[2]
    worker_root = repo_root / "services" / "freecad-worker"
    if str(worker_root) not in sys.path:
        sys.path.insert(0, str(worker_root))
    module_path = worker_root / "worker" / "jobs.py"
    spec = importlib.util.spec_from_file_location("worker_jobs_macro_semantic_validation_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_macro_validation_rejects_export_calls_before_freecad_execution(monkeypatch):
    jobs = _load_jobs_module()
    uploads = []
    prompts = []
    responses = iter([
        'import FreeCAD\ndoc = FreeCAD.newDocument("Model")\nbox = doc.addObject("Part::Box", "Box")\nFreeCAD.export([box], "bad.FCStd")\n',
        'import FreeCAD as App\nimport Part\ndoc = App.newDocument("Model")\nbox = doc.addObject("Part::Box", "Result")\nbox.Length = 10\nbox.Width = 2\nbox.Height = 1\ndoc.recompute()\n',
    ])

    def fake_chat(messages, **_kwargs):
        prompts.append(messages[-1]["content"])
        return next(responses)

    monkeypatch.setattr(jobs, "chat", fake_chat)
    monkeypatch.setattr(jobs, "_resolve_freecadcmd", lambda: "/usr/bin/freecadcmd")
    monkeypatch.setattr(jobs, "put_object", lambda key, data, content_type="application/octet-stream": uploads.append({"key": key, "data": data}))

    called = {"count": 0}
    def fake_run_freecad_headless(**_kwargs):
        called["count"] += 1
        outdir = Path(_kwargs["outdir"])
        (outdir / "model.FCStd").write_bytes(b"fcstd")
        return "ok", "", 0

    monkeypatch.setattr(jobs, "_run_freecad_headless", fake_run_freecad_headless)

    result = jobs.run_repair_loop_job(
        job_id="job-1",
        session_id="session-1",
        user_message_id="message-1",
        prompt="make a box",
        export={"fcstd": True, "step": False, "stl": False},
        max_repair_iterations=2,
    )

    assert result["passed"] is True
    assert called["count"] == 1
    assert any("must not call export or save APIs itself" in p for p in prompts[1:])


def test_macro_validation_flags_freecad_export_call():
    jobs = _load_jobs_module()
    err = jobs._macro_validation_error('import FreeCAD\nFreeCAD.export([], "x.FCStd")\n')
    assert err is not None
    assert "must not be used" in err or "not a valid export API" in err
