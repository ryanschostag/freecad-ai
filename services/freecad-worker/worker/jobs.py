import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from worker.llm import chat
from worker.prompts import build_generate_prompt, build_repair_prompt
from worker.storage import put_object


RUNNER_START_MARKER = "RUNNER:START"
RUNNER_DONE_MARKER = "RUNNER:DONE"
_TEMPLATE_ROLE_RE = re.compile(r"<\|im_start\|>(system|user|assistant)\n", re.IGNORECASE)


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


def _artifact_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".fcstd": "application/octet-stream",
        ".step": "model/step",
        ".stp": "model/step",
        ".stl": "model/stl",
    }.get(suffix, "application/octet-stream")


def _artifact_kind_for_model(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".fcstd": "freecad_model_fcstd",
        ".step": "freecad_model_step",
        ".stp": "freecad_model_step",
        ".stl": "freecad_model_stl",
    }.get(suffix, "freecad_model_file")


def _detect_freecadcmd() -> str | None:
    for candidate in ("freecadcmd", "FreeCADCmd", "/usr/bin/freecadcmd", "/usr/bin/FreeCADCmd"):
        resolved = shutil.which(candidate) if "/" not in candidate else candidate
        if resolved and os.path.exists(resolved):
            return resolved
    return None


def _collect_model_artifacts(
    *,
    session_id: str,
    user_message_id: str,
    outdir: str,
    export: dict[str, bool] | None = None,
) -> list[dict]:
    artifacts: list[dict] = []
    outdir_path = Path(outdir)
    if not outdir_path.exists():
        return artifacts

    requested_suffixes = []
    export_flags = export or {"fcstd": True, "step": True, "stl": False}
    if export_flags.get("fcstd", True):
        requested_suffixes.append(".fcstd")
    if export_flags.get("step", True):
        requested_suffixes.extend([".step", ".stp"])
    if export_flags.get("stl", False):
        requested_suffixes.append(".stl")

    candidates: dict[str, Path] = {}
    for path in sorted(outdir_path.iterdir()):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix not in {".fcstd", ".step", ".stp", ".stl"}:
            continue
        if requested_suffixes and suffix not in requested_suffixes:
            continue
        candidates.setdefault(suffix, path)

    preferred_order = [".fcstd", ".step", ".stp", ".stl"]
    for suffix in preferred_order:
        path = candidates.get(suffix)
        if not path:
            continue
        normalized_ext = ".step" if suffix == ".stp" else path.suffix
        key = f"sessions/{session_id}/models/{user_message_id}{normalized_ext}"
        artifacts.append(
            _put_artifact(
                key=key,
                data=path.read_bytes(),
                kind=_artifact_kind_for_model(path),
                content_type=_artifact_content_type(path),
            )
        )
    return artifacts


def _runner_markers(stdout: str, stderr: str) -> tuple[bool, bool]:
    start_seen = False
    done_seen = False
    for line in f"{stdout}\n{stderr}".splitlines():
        stripped = line.strip()
        if stripped == RUNNER_START_MARKER:
            start_seen = True
        elif stripped == RUNNER_DONE_MARKER:
            done_seen = True
    return start_seen, done_seen


def _runner_markers_seen(stdout: str, stderr: str) -> bool:
    start_seen, done_seen = _runner_markers(stdout, stderr)
    return start_seen and done_seen


def _llm_generation_budget(timeout_seconds: int, llm_max_tokens: int | None = None) -> dict[str, int | float]:
    """Keep the LLM call inside the enclosing RQ job timeout.

    The queue timeout is enforced outside Python by RQ's work-horse process.
    If we allow multiple long HTTP attempts, the work horse can be killed before
    chat() returns or raises, leaving no diagnostics or artifacts. Reserve a
    small slice for uploads/cleanup and use a single bounded attempt.
    """
    total = max(60, int(timeout_seconds or 300))
    reserved_for_cleanup = min(180, max(45, total // 6))
    request_timeout = max(30, total - reserved_for_cleanup)
    configured_max_tokens = int(llm_max_tokens) if llm_max_tokens is not None else 1200
    max_tokens = max(1, configured_max_tokens)
    return {
        "timeout_s": float(request_timeout),
        "max_attempts": 1,
        "max_tokens": max_tokens,
    }


def _looks_like_chat_template(prompt: str) -> bool:
    s = prompt.strip()
    return "<|im_start|>" in s and "<|im_end|>" in s


def _parse_chat_template_prompt(prompt: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    matches = list(_TEMPLATE_ROLE_RE.finditer(prompt))
    if not matches:
        return []

    for idx, match in enumerate(matches):
        role = match.group(1).lower()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(prompt)
        block = prompt[start:end]
        content = block.split("<|im_end|>", 1)[0].strip()
        if role == "assistant" and not content:
            continue
        messages.append({"role": role, "content": content})
    return messages


def _build_generation_messages(prompt: str, mode: str | None, units: str | None, tolerance_mm: float | None) -> list[dict[str, str]]:
    if _looks_like_chat_template(prompt):
        parsed = _parse_chat_template_prompt(prompt)
        if parsed:
            return parsed
    return build_generate_prompt(prompt, mode or "design", units or "mm", tolerance_mm if tolerance_mm is not None else 0.1)


def _compile_macro_or_error(macro_code: str, filename: str) -> str | None:
    try:
        compile(macro_code, filename, "exec")
        return None
    except SyntaxError as exc:
        maybe_truncated = ""
        if exc.lineno and exc.lineno >= max(1, len(macro_code.splitlines()) - 2):
            maybe_truncated = "; generation may have been truncated"
        return f"generated macro failed syntax check: SyntaxError: {exc.msg} (line {exc.lineno}){maybe_truncated}"


def _generate_macro_with_repairs(
    *,
    prompt: str,
    mode: str | None,
    units: str | None,
    tolerance_mm: float | None,
    llm_budget: dict[str, int | float],
    max_repair_iterations: int,
) -> tuple[str, str, list[str], int]:
    issues: list[str] = []
    messages = _build_generation_messages(prompt, mode, units, tolerance_mm)
    last_macro = ""
    attempts = max(1, int(max_repair_iterations or 1))

    for iteration in range(1, attempts + 1):
        try:
            macro_code = chat(
                messages,
                timeout_s=float(llm_budget["timeout_s"]),
                max_attempts=int(llm_budget["max_attempts"]),
                max_tokens=int(llm_budget["max_tokens"]),
                stop=["<|im_end|>", "</s>", "<|endoftext|>"],
            )
        except Exception as exc:
            reason = f"llm request failed: {type(exc).__name__}: {exc}"
            issues.append(reason)
            return "", reason, issues, iteration

        raw_macro_code = macro_code if isinstance(macro_code, str) else ""
        last_macro = raw_macro_code
        if not raw_macro_code.strip():
            reason = "llm returned an empty response"
            issues.append(reason)
            return "", reason, issues, iteration

        syntax_issue = _compile_macro_or_error(raw_macro_code, f"generation_{iteration}.py")
        if syntax_issue is None:
            return raw_macro_code, "", issues, iteration

        issues.append(syntax_issue)
        if iteration >= attempts:
            return raw_macro_code, syntax_issue, issues, iteration

        repair_issue = {
            "rule_code": "python_syntax_error",
            "object_name": f"generation_{iteration}.py",
            "message": syntax_issue,
        }
        messages = build_repair_prompt(
            prompt,
            raw_macro_code,
            [repair_issue],
            units or "mm",
            tolerance_mm if tolerance_mm is not None else 0.1,
        )

    return last_macro, "llm returned no usable macro", issues, attempts


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
    llm_max_tokens: int | None = None,
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

    artifacts: list[dict] = []
    issues: list[str] = []
    placeholder_reason: str | None = None
    render_result: dict[str, object] = {
        "attempted": False,
        "executed": False,
        "returncode": None,
        "stdout": "",
        "stderr": "",
        "freecadcmd": None,
        "runner_start_seen": False,
        "runner_done_seen": False,
        "runner_markers_seen": False,
        "uploaded_model_kinds": [],
    }

    llm_budget = _llm_generation_budget(timeout_seconds, llm_max_tokens)

    raw_macro_code, generation_reason, generation_issues, generation_attempts = _generate_macro_with_repairs(
        prompt=prompt,
        mode=mode,
        units=units,
        tolerance_mm=tolerance_mm,
        llm_budget=llm_budget,
        max_repair_iterations=max_repair_iterations,
    )
    issues.extend(generation_issues)

    if generation_reason:
        placeholder_reason = generation_reason
        macro_code = (
            "# Generated macro was empty; writing a safe placeholder.\n"
            "import FreeCAD as App\n"
            "App.newDocument('Model')\n"
        )
    else:
        macro_code = raw_macro_code

    macro_bytes = macro_code.encode("utf-8")
    macro_key = f"sessions/{session_id}/macros/{user_message_id}.gen0.py"
    artifacts.append(_put_artifact(key=macro_key, data=macro_bytes, kind="freecad_macro_py", content_type="text/x-python"))

    if not placeholder_reason:
        render_result["attempted"] = True
        freecadcmd = _detect_freecadcmd()
        render_result["freecadcmd"] = freecadcmd
        if freecadcmd:
            with tempfile.TemporaryDirectory() as tmpdir:
                macro_path = Path(tmpdir) / f"{user_message_id}.py"
                macro_path.write_text(macro_code, encoding="utf-8")
                model_outdir = Path(tmpdir) / "models"
                model_outdir.mkdir(parents=True, exist_ok=True)
                try:
                    stdout, stderr, returncode = _run_freecad_headless(
                        freecadcmd,
                        str(macro_path),
                        str(model_outdir),
                        export_flags,
                        timeout_seconds,
                    )
                    runner_start_seen, runner_done_seen = _runner_markers(stdout, stderr)
                    render_result.update({
                        "executed": True,
                        "stdout": stdout,
                        "stderr": stderr,
                        "returncode": returncode,
                        "runner_start_seen": runner_start_seen,
                        "runner_done_seen": runner_done_seen,
                        "runner_markers_seen": runner_start_seen and runner_done_seen,
                    })
                    model_artifacts = _collect_model_artifacts(
                        session_id=session_id,
                        user_message_id=user_message_id,
                        outdir=str(model_outdir),
                        export=export_flags,
                    )
                    artifacts.extend(model_artifacts)
                    render_result["uploaded_model_kinds"] = [artifact["kind"] for artifact in model_artifacts]
                    if returncode != 0:
                        issues.append(f"freecad execution failed with return code {returncode}")
                    elif runner_start_seen and not runner_done_seen and not model_artifacts:
                        issues.append("freecad runner started but did not complete")
                    elif not runner_start_seen and not runner_done_seen and not model_artifacts:
                        issues.append("freecad process returned success but runner script did not execute")
                    if not model_artifacts:
                        issues.append("freecad execution completed but did not produce any model artifacts")
                except Exception as exc:
                    render_result["stderr"] = f"{type(exc).__name__}: {exc}"
                    issues.append(f"freecad execution failed: {type(exc).__name__}: {exc}")
        else:
            issues.append("freecadcmd not found; skipping model export")

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
        "llm_max_tokens": llm_budget["max_tokens"],
        "llm_budget": llm_budget,
        "generation_attempts": generation_attempts,
        "placeholder_used": bool(placeholder_reason),
        "placeholder_reason": placeholder_reason,
        "raw_macro_chars": len(raw_macro_code),
        "generated_macro_chars": len(macro_code),
        "render": render_result,
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
        "iterations": generation_attempts,
        "issues": issues,
        "artifacts": artifacts,
    }


def _runner_script() -> str:
    return r'''
import os
import traceback
import FreeCAD as App


def main():
    print("RUNNER:START")
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

    print("RUNNER:DONE")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
'''


def _build_console_exec_input(runner_path: str) -> str:
    return (
        "exec(compile(open(" + repr(runner_path) + ", 'r', encoding='utf-8').read(), "
        + repr(runner_path)
        + ", 'exec'))\n"
    )


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

        attempts = [
            {"cmd": [freecadcmd, str(runner_path)], "input": None},
            {"cmd": [freecadcmd, "-c"], "input": _build_console_exec_input(str(runner_path))},
        ]
        last = None
        for attempt in attempts:
            try:
                p = subprocess.run(
                    attempt["cmd"],
                    input=attempt["input"],
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    env=env,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("FreeCAD execution timed out") from exc
            last = p
            if p.returncode != 0 or _runner_markers_seen(p.stdout, p.stderr):
                return p.stdout, p.stderr, p.returncode

        assert last is not None
        return last.stdout, last.stderr, last.returncode


def main():
    raise SystemExit("worker.jobs.main is not intended to be called directly")
