from __future__ import annotations
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from typing import Any

import httpx

from worker.storage import put_object
from worker.llm import chat
from worker.prompts import build_generate_prompt, build_repair_prompt
from worker.settings import settings


def _notify_api_started(job_id: str) -> None:
    """Persist queued -> started outside Redis.

    This is best-effort; job execution should continue even if the API is down.
    """
    try:
        url = f"{settings.api_base_url.rstrip('/')}/internal/jobs/{job_id}/started"
        httpx.post(url, json={"ts": datetime.now(timezone.utc).isoformat()}, timeout=2.0)
    except Exception:
        # Best-effort: ignore
        return


def _notify_api_complete(
    job_id: str,
    status: str,
    result: dict[str, Any] | None,
    error: dict[str, Any] | None,
    artifacts: list[dict[str, Any]] | None = None,
) -> None:
    """Persist started -> finished/failed and the final result outside Redis."""
    try:
        url = f"{settings.api_base_url.rstrip('/')}/internal/jobs/{job_id}/complete"
        payload = {
            "status": status,
            "ts": datetime.now(timezone.utc).isoformat(),
            "result": result,
            "error": error,
            "artifacts": artifacts or [],
        }
        httpx.post(url, json=payload, timeout=10.0)
    except Exception:
        return

def _sha256(b: bytes) -> str:
    h = hashlib.sha256(); h.update(b); return h.hexdigest()

def _taxonomy_from_output(stdout: str, stderr: str) -> list[dict[str, Any]]:
    text = (stdout or "") + "\n" + (stderr or "")
    issues: list[dict[str, Any]] = []
    # Common Sketcher wording (varies by version)
    if "over-constrained" in text or "overconstrained" in text:
        issues.append({"rule_code":"CONSTRAINT_OVERCONSTRAINED","object_name":None,"message":"Sketch over-constrained","severity":"error"})
    if "under-constrained" in text or "underconstrained" in text:
        issues.append({"rule_code":"CONSTRAINT_UNDERCONSTRAINED","object_name":None,"message":"Sketch under-constrained","severity":"warning"})
    if "redundant" in text and "constraint" in text:
        issues.append({"rule_code":"CONSTRAINT_REDUNDANT","object_name":None,"message":"Redundant constraint detected","severity":"warning"})
    return issues

def _runner_script() -> str:
    return r"""import sys, os, traceback, json
import FreeCAD as App
import json

def parse_args(argv):
    out = {"macro": None, "outdir": None, "fcstd": "1", "step":"1", "stl":"0"}
    it = iter(argv[1:])
    for a in it:
        if a == "--macro":
            out["macro"] = next(it, None)
        elif a == "--outdir":
            out["outdir"] = next(it, None)
        elif a == "--fcstd":
            out["fcstd"] = next(it, "1")
        elif a == "--step":
            out["step"] = next(it, "1")
        elif a == "--stl":
            out["stl"] = next(it, "0")
    return out

def main():
    args = parse_args(sys.argv)
    macro_path = args["macro"]
    outdir = args["outdir"] or os.getcwd()
    os.makedirs(outdir, exist_ok=True)

    # Ensure a document exists
    if App.ActiveDocument is None:
        App.newDocument("Model")

    # Execute macro
    g = {"App": App}
    with open(macro_path, "r", encoding="utf-8") as f:
        code = f.read()
    exec(compile(code, macro_path, "exec"), g, g)

    doc = App.ActiveDocument
    # Recompute and basic validation
    try:
        doc.recompute()
    except Exception as e:
        print("VALIDATION:FREECAD_EXCEPTION:" + str(e))

    # Print sketch solver info if available
    for obj in list(doc.Objects):
        try:
            if getattr(obj, "TypeId", "").startswith("Sketcher::SketchObject"):
                if hasattr(obj, "solve"):
                    obj.solve()
                msgs = getattr(obj, "SolverMessages", None)
                if msgs:
                    for m in msgs:
                        print("VALIDATION:SKETCH_SOLVER:" + str(m))

                # Emit sketch status (best-effort; APIs differ by version)
                try:
                    status = {
                        "name": getattr(obj, "Name", None),
                        "label": getattr(obj, "Label", None),
                        "dof": getattr(obj, "DegreeOfFreedom", None),
                        "constraints": getattr(obj, "ConstraintCount", None),
                        "geometries": getattr(obj, "GeometryCount", None),
                    }
                    print("VALIDATION:SKETCH_STATUS:" + json.dumps(status))
                except Exception as e:
                    print("VALIDATION:SKETCH_STATUS_ERROR:" + str(e))
        except Exception as e:
            print("VALIDATION:SKETCH_CHECK_EXCEPTION:" + str(e))

    # Save + export
    base = os.path.join(outdir, "model")
    if args["fcstd"] == "1":
        doc.saveAs(base + ".FCStd")
    export_objs = [o for o in doc.Objects if hasattr(o, "Shape")]
    if args["step"] == "1":
        try:
            import Import
            Import.export(export_objs, base + ".step")
        except Exception as e:
            print("VALIDATION:EXPORT_FAILED:STEP:" + str(e))
    if args["stl"] == "1":
        try:
            import Mesh
            Mesh.export(export_objs, base + ".stl")
        except Exception as e:
            print("VALIDATION:EXPORT_FAILED:STL:" + str(e))

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        traceback.print_exc()
        raise
"""

def _run_freecad_headless(
    macro_code: str,
    export: dict[str,bool],
    timeout_seconds: int,
) -> tuple:
    """Returns: passed, issues, produced_files{name->bytes}, stdout, stderr"""
    freecadcmd = shutil.which("freecadcmd")
    if not freecadcmd:
        issues=[{"rule_code":"FREECAD_NOT_INSTALLED","object_name":None,"message":"freecadcmd not found","severity":"error"}]
        return False, issues, {}, "", ""

    with tempfile.TemporaryDirectory() as td:
        macro_path = os.path.join(td, "macro.py")
        runner_path = os.path.join(td, "runner.py")
        outdir = os.path.join(td, "out")
        os.makedirs(outdir, exist_ok=True)

        with open(macro_path, "w", encoding="utf-8") as f:
            f.write(macro_code)
        with open(runner_path, "w", encoding="utf-8") as f:
            f.write(_runner_script())

        cmd = [
            freecadcmd,
            runner_path,
            "--macro", macro_path,
            "--outdir", outdir,
            "--fcstd", "1" if export.get("fcstd", True) else "0",
            "--step", "1" if export.get("step", True) else "0",
            "--stl", "1" if export.get("stl", False) else "0",
        ]

        try:
            p = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            stdout, stderr = p.stdout, p.stderr
        except subprocess.TimeoutExpired as e:
            issues = [{
                "rule_code": "FREECAD_TIMEOUT",
                "object_name": None,
                "message": f"freecadcmd exceeded timeout_seconds={timeout_seconds}",
                "severity": "error",
            }]
            return False, issues, {}, (e.stdout or ""), (e.stderr or "")

        stdout, stderr = p.stdout, p.stderr

        issues = _taxonomy_from_output(stdout, stderr)

        # Parse our explicit VALIDATION markers
        for line in (stdout or "").splitlines():
            if line.startswith("VALIDATION:SKETCH_STATUS:"):
                try:
                    payload = json.loads(line.replace("VALIDATION:SKETCH_STATUS:","",1))
                    # If DoF is present and >0, flag underconstrained as warning.
                    dof = payload.get("dof")
                    name = payload.get("name") or payload.get("label")
                    if isinstance(dof, int) and dof > 0:
                        issues.append({"rule_code":"CONSTRAINT_UNDERCONSTRAINED","object_name":name,"message":f"Sketch has DoF={dof}","severity":"warning"})
                except Exception:
                    pass

            if line.startswith("VALIDATION:FREECAD_EXCEPTION:"):
                issues.append({"rule_code":"FREECAD_EXCEPTION","object_name":None,"message":line.split(":",2)[2],"severity":"error"})
            if line.startswith("VALIDATION:EXPORT_FAILED:"):
                issues.append({"rule_code":"EXPORT_FAILED","object_name":None,"message":line.replace("VALIDATION:",""),"severity":"error"})
            if line.startswith("VALIDATION:SKETCH_SOLVER:"):
                msg=line.replace("VALIDATION:SKETCH_SOLVER:","").strip()
                if "over" in msg and "con" in msg:
                    issues.append({"rule_code":"CONSTRAINT_OVERCONSTRAINED","object_name":None,"message":msg,"severity":"error"})
                elif "under" in msg and "con" in msg:
                    issues.append({"rule_code":"CONSTRAINT_UNDERCONSTRAINED","object_name":None,"message":msg,"severity":"warning"})

        passed = (p.returncode == 0) and not any(i["rule_code"] in {"FREECAD_EXCEPTION","FREECAD_NOT_INSTALLED","EXPORT_FAILED","CONSTRAINT_OVERCONSTRAINED"} for i in issues)

        produced: dict[str, bytes] = {}
        for fn in ["model.FCStd","model.step","model.stl"]:
            fp=os.path.join(outdir, fn)
            if os.path.exists(fp):
                with open(fp, "rb") as f:
                    produced[fn]=f.read()

        return passed, issues, produced, stdout, stderr

def run_repair_loop_job(
    job_id: str,
    session_id: str,
    user_message_id: str,
    prompt: str,
    mode: str,
    export: dict[str,bool],
    units: str,
    tolerance_mm: float,
    max_repair_iterations: int = 3,
    timeout_seconds: int = 300,
) -> dict:
    ts = datetime.now(timezone.utc).isoformat()
    _notify_api_started(job_id)

    artifacts: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    try:
        # 1) Generate macro from local LLM
        messages = build_generate_prompt(prompt, mode, units, tolerance_mm)
        macro_code = chat(messages)

        macro_bytes = macro_code.encode("utf-8")
        macro_key = f"sessions/{session_id}/macros/{user_message_id}.gen0.py"
        put_object(macro_key, macro_bytes, content_type="text/x-python")
        artifacts.append(
            {
                "kind": "freecad_macro_py",
                "object_key": macro_key,
                "sha256": _sha256(macro_bytes),
                "bytes": len(macro_bytes),
            }
        )

        for i in range(max_repair_iterations):
            passed, issues, produced_files, out, err = _run_freecad_headless(
                macro_code,
                export,
                timeout_seconds,
            )

            report = {
                "job_id": job_id,
                "session_id": session_id,
                "user_message_id": user_message_id,
                "iteration_index": i,
                "passed": passed,
                "issues": issues,
                "stdout_tail": (out or "")[-5000:],
                "stderr_tail": (err or "")[-5000:],
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            report_bytes = json.dumps(report, indent=2).encode("utf-8")
            report_key = f"sessions/{session_id}/reports/{user_message_id}.validation.{i}.json"
            put_object(report_key, report_bytes, "application/json")
            artifacts.append(
                {
                    "kind": "validation_report_json",
                    "object_key": report_key,
                    "sha256": _sha256(report_bytes),
                    "bytes": len(report_bytes),
                }
            )

            # Upload produced files (if any)
            for name, data in produced_files.items():
                k = f"sessions/{session_id}/artifacts/{user_message_id}/iter{i}/{name}"
                put_object(k, data, content_type="application/octet-stream")
                kind = (
                    "freecad_fcstd"
                    if name.lower().endswith(".fcstd")
                    else ("cad_step" if name.lower().endswith(".step") else "mesh_stl")
                )
                artifacts.append(
                    {
                        "kind": kind,
                        "object_key": k,
                        "sha256": _sha256(data),
                        "bytes": len(data),
                    }
                )

            if passed:
                result = {
                    "job_id": job_id,
                    "session_id": session_id,
                    "user_message_id": user_message_id,
                    "passed": True,
                    "iterations": i + 1,
                    "issues": issues,
                    "artifacts": artifacts,
                    "ts": ts,
                }
                _notify_api_complete(job_id, status="finished", result=result, error=None)
                return result

            # 2) Repair using constraint-aware prompt
            repair_msgs = build_repair_prompt(prompt, macro_code, issues, units, tolerance_mm)
            macro_code = chat(repair_msgs)

            macro_bytes = macro_code.encode("utf-8")
            macro_key = f"sessions/{session_id}/macros/{user_message_id}.repair{i+1}.py"
            put_object(macro_key, macro_bytes, content_type="text/x-python")
            artifacts.append(
                {
                    "kind": "freecad_macro_py",
                    "object_key": macro_key,
                    "sha256": _sha256(macro_bytes),
                    "bytes": len(macro_bytes),
                }
            )

        # Exhausted repair attempts
        result = {
            "job_id": job_id,
            "session_id": session_id,
            "user_message_id": user_message_id,
            "passed": False,
            "iterations": max_repair_iterations,
            "issues": issues,
            "artifacts": artifacts,
            "ts": ts,
        }
        _notify_api_complete(job_id, status="finished", result=result, error=None)
        return result

    except Exception as e:
        err_payload = {"message": str(e), "type": e.__class__.__name__}
        _notify_api_complete(job_id, status="failed", result=None, error=err_payload)
        raise
