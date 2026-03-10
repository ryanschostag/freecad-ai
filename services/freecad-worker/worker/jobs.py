import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from worker.llm import chat
from worker.storage import put_object


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _put_artifact(*, key: str, data: bytes, kind: str, content_type: str = "application/octet-stream") -> dict:
    put_object(key, data, content_type=content_type)
    return {
        "kind": kind,
        "object_key": key,
        "bytes": len(data),
        "sha256": _sha256_bytes(data),
    }




def _llm_generation_budget(timeout_seconds: int) -> dict[str, int | float]:
    """Keep the LLM call inside the enclosing RQ job timeout.

    The queue timeout is enforced outside Python by RQ's work-horse process.
    If we allow multiple long HTTP attempts, the work horse can be killed before
    chat() returns or raises, leaving no diagnostics or artifacts. Reserve a
    small slice for uploads/cleanup and use a single bounded attempt.
    """
    total = max(60, int(timeout_seconds or 300))
    reserved_for_cleanup = min(120, max(30, total // 8))
    request_timeout = max(30, total - reserved_for_cleanup)
    return {
        "timeout_s": float(request_timeout),
        "max_attempts": 1,
        "max_tokens": 400,
    }

def run_repair_loop_job(
    *,
    job_id: str,
    session_id: str,
    user_message_id: str,
    prompt: str,
    mode: str | None = None,
    export: list[str] | dict | None = None,
    units: str | None = None,
    tolerance_mm: float | None = None,
    max_repair_iterations: int = 3,
    timeout_seconds: int = 300,
):
    """RQ entrypoint executed by the freecad-worker container."""

    export_list: list[str] = []
    export_flags: dict[str, bool] = {"fcstd": True, "step": True, "stl": False}
    if isinstance(export, list):
        export_list = [str(x).strip().lower() for x in export if str(x).strip()]
        export_flags = {"fcstd": "fcstd" in export_list, "step": "step" in export_list, "stl": "stl" in export_list}
    elif isinstance(export, str):
        export_list = [x.strip().lower() for x in export.split(",") if x.strip()]
        export_flags = {"fcstd": "fcstd" in export_list, "step": "step" in export_list, "stl": "stl" in export_list}
    elif isinstance(export, dict):
        export_list = [k.strip().lower() for k, v in export.items() if v]
        export_flags = {
            "fcstd": bool(export.get("fcstd", True)),
            "step": bool(export.get("step", True)),
            "stl": bool(export.get("stl", False)),
        }

    messages = [
        {
            "role": "system",
            "content": "You are a CAD assistant. Output ONLY valid Python code for a FreeCAD macro. Do not wrap in markdown fences. Do not include explanations.",
        },
        {
            "role": "user",
            "content": f"Prompt: {prompt}\nUnits: {units or 'mm'}\nTolerance(mm): {tolerance_mm or 0.1}\n",
        },
    ]

    artifacts: list[dict] = []
    issues: list[str] = []
    placeholder_reason: str | None = None

    llm_budget = _llm_generation_budget(timeout_seconds)

    try:
        macro_code = chat(
            messages,
            timeout_s=float(llm_budget["timeout_s"]),
            max_attempts=int(llm_budget["max_attempts"]),
            max_tokens=int(llm_budget["max_tokens"]),
            stop=["<|im_end|>", "</s>", "```"],
        )
    except Exception as exc:
        macro_code = ""
        placeholder_reason = f"llm request failed: {type(exc).__name__}: {exc}"
        issues.append(placeholder_reason)
    raw_macro_code = macro_code if isinstance(macro_code, str) else ""

    if not raw_macro_code.strip() and not placeholder_reason:
        placeholder_reason = "llm returned an empty response"
        issues.append(placeholder_reason)

    if placeholder_reason:
        macro_code = (
            "# Generated macro was empty; writing a safe placeholder.\n"
            "import FreeCAD as App\n"
            "App.newDocument('Model')\n"
        )

    macro_bytes = macro_code.encode("utf-8")
    macro_key = f"sessions/{session_id}/macros/{user_message_id}.gen0.py"
    artifacts.append(_put_artifact(key=macro_key, data=macro_bytes, kind="freecad_macro_py", content_type="text/x-python"))

    diag = {
        "job_id": job_id,
        "session_id": session_id,
        "user_message_id": user_message_id,
        "mode": mode,
        "prompt": prompt,
        "units": units or "mm",
        "tolerance_mm": tolerance_mm if tolerance_mm is not None else 0.1,
        "export": export_flags,
        "export_list": export_list,
        "max_repair_iterations": max_repair_iterations,
        "timeout_seconds": timeout_seconds,
        "llm_budget": llm_budget,
        "placeholder_used": bool(placeholder_reason),
        "placeholder_reason": placeholder_reason,
        "raw_macro_chars": len(raw_macro_code),
        "generated_macro_chars": len(macro_code),
        "issues": issues,
    }
    diag_key = f"sessions/{session_id}/diagnostics/{user_message_id}.diagnostics.json"
    artifacts.append(
        _put_artifact(
            key=diag_key,
            data=(json.dumps(diag, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            kind="job_diagnostics_json",
            content_type="application/json",
        )
    )

    if placeholder_reason:
        reason_key = f"sessions/{session_id}/diagnostics/{user_message_id}.empty_macro_reason.txt"
        artifacts.append(
            _put_artifact(
                key=reason_key,
                data=(placeholder_reason + "\n").encode("utf-8"),
                kind="job_reason_txt",
                content_type="text/plain",
            )
        )

    return {
        "job_id": job_id,
        "session_id": session_id,
        "user_message_id": user_message_id,
        "passed": not bool(placeholder_reason),
        "iterations": 1,
        "issues": issues,
        "artifacts": artifacts,
    }


def _runner_script() -> str:
    return r"""
import os, traceback
import FreeCAD as App

def main():
    macro_path = os.environ.get("CAD_MACRO_PATH")
    outdir = os.environ.get("CAD_OUTDIR") or os.getcwd()
    export_fcstd = os.environ.get("CAD_EXPORT_FCSTD", "1")
    export_step = os.environ.get("CAD_EXPORT_STEP", "1")
    export_stl = os.environ.get("CAD_EXPORT_STL", "0")

    if not macro_path:
        raise RuntimeError("CAD_MACRO_PATH env var not set")

    os.makedirs(outdir, exist_ok=True)

    if App.ActiveDocument is None:
        App.newDocument("Model")

    g = {"App": App}
    with open(macro_path, "r", encoding="utf-8") as f:
        code = f.read()
    exec(compile(code, macro_path, "exec"), g, g)

    doc = App.ActiveDocument
    try:
        doc.recompute()
    except Exception as e:
        print("VALIDATION:FREECAD_EXCEPTION:" + str(e))

    base = os.path.join(outdir, "model")

    if export_fcstd == "1":
        doc.saveAs(base + ".FCStd")

    export_objs = [o for o in doc.Objects if hasattr(o, "Shape")]

    if export_step == "1":
        try:
            import Import
            Import.export(export_objs, base + ".step")
        except Exception as e:
            print("VALIDATION:EXPORT_FAILED:STEP:" + str(e))

    if export_stl == "1":
        try:
            import Mesh
            Mesh.export(export_objs, base + ".stl")
        except Exception as e:
            print("VALIDATION:EXPORT_FAILED:STL:" + str(e))

if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
"""


def _run_freecad_headless(freecadcmd: str, macro_path: str, outdir: str, export: dict, timeout_seconds: int):
    runner_code = _runner_script()

    with tempfile.TemporaryDirectory() as tmpdir:
        runner_path = Path(tmpdir) / "runner.py"
        runner_path.write_text(runner_code, encoding="utf-8")

        env = os.environ.copy()
        env.update(
            {
                "CAD_MACRO_PATH": macro_path,
                "CAD_OUTDIR": outdir,
                "CAD_EXPORT_FCSTD": "1" if export.get("fcstd", True) else "0",
                "CAD_EXPORT_STEP": "1" if export.get("step", True) else "0",
                "CAD_EXPORT_STL": "1" if export.get("stl", False) else "0",
            }
        )

        cmd = [freecadcmd, "-c", str(runner_path)]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds, env=env)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("FreeCAD execution timed out") from exc

        return p.stdout, p.stderr, p.returncode


def main():
    raise SystemExit("worker.jobs.main is not intended to be called directly")
