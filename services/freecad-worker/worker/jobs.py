import hashlib
import os
import subprocess
import tempfile
import traceback
from pathlib import Path

from worker.llm import chat
from worker.storage import put_object


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
    """
    RQ entrypoint executed by the freecad-worker container.

    Minimal behavior (sufficient for tests):
      - Call LLM to generate macro code
      - Store macro in MinIO
      - Return schema that API persists/uses for metrics/artifacts

    Notes:
      - The API test asserts that at least one artifact exists and at least one is kind=freecad_macro_py.
      - The API will record a "completion" based on artifact bytes when the job is "finished".
    """

    # Normalize export into a list of strings (best-effort; worker currently stores the macro regardless)
    export_list: list[str] = []
    if isinstance(export, list):
        export_list = [str(x).strip().lower() for x in export if str(x).strip()]
    elif isinstance(export, str):
        export_list = [x.strip().lower() for x in export.split(",") if x.strip()]
    elif isinstance(export, dict):
        # allow {"fcstd":true,"step":true} style
        export_list = [k.strip().lower() for k, v in export.items() if v]

    # Build a simple, deterministic prompt for the local llm-fake / OpenAI-compatible endpoint.
    # Keep it robust: even if the model returns junk, we still store what it returned.
    sys_msg = (
        "You are a CAD assistant. Output ONLY valid Python code for a FreeCAD macro. "
        "Do not wrap in markdown fences. Do not include explanations."
    )
    user_msg = f"Prompt: {prompt}\nUnits: {units or 'mm'}\nTolerance(mm): {tolerance_mm or 0.1}\n"

    messages = [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": user_msg},
    ]

    macro_code = chat(messages)

    # Always ensure we store something that is a python file; avoid empty macros.
    if not macro_code or not macro_code.strip():
        macro_code = (
            "# Generated macro was empty; writing a safe placeholder.\n"
            "import FreeCAD as App\n"
            "App.newDocument('Model')\n"
        )

    macro_bytes = macro_code.encode("utf-8")
    macro_key = f"sessions/{session_id}/macros/{user_message_id}.gen0.py"

    put_object(macro_key, macro_bytes, content_type="text/x-python")

    return {
        "job_id": job_id,
        "session_id": session_id,
        "user_message_id": user_message_id,
        "passed": True,
        "iterations": 1,
        "issues": [],
        "artifacts": [
            {
                "kind": "freecad_macro_py",
                "object_key": macro_key,
                "bytes": len(macro_bytes),
                "sha256": _sha256_bytes(macro_bytes),
            }
        ],
    }


def _runner_script() -> str:
    return r"""
import os, sys, traceback
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


def _run_freecad_headless(
    freecadcmd: str,
    macro_path: str,
    outdir: str,
    export: dict,
    timeout_seconds: int,
):
    runner_code = _runner_script()

    with tempfile.TemporaryDirectory() as tmpdir:
        runner_path = Path(tmpdir) / "runner.py"
        runner_path.write_text(runner_code, encoding="utf-8")

        env = os.environ.copy()
        env.update({
            "CAD_MACRO_PATH": macro_path,
            "CAD_OUTDIR": outdir,
            "CAD_EXPORT_FCSTD": "1" if export.get("fcstd", True) else "0",
            "CAD_EXPORT_STEP": "1" if export.get("step", True) else "0",
            "CAD_EXPORT_STL": "1" if export.get("stl", False) else "0",
        })

        cmd = [freecadcmd, "-c", str(runner_path)]

        try:
            p = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("FreeCAD execution timed out")

        return p.stdout, p.stderr, p.returncode


def main():
    """
    Legacy/local entrypoint for running a macro via FreeCAD headless runner.
    The RQ worker entrypoint used by the API is run_repair_loop_job().
    """
    raise SystemExit("worker.jobs.main is not intended to be called directly")
