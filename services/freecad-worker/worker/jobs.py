import os
import subprocess
import tempfile
import traceback
from pathlib import Path

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
