import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

from worker.llm import chat, _normalize_generated_text
from worker.storage import put_object
from worker.settings import settings
from worker.prompts import build_compact_generate_prompt, build_compact_retry_prompt


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




def _post_internal_job_update(*, job_id: str, path: str, payload: dict) -> None:
    base_url = (settings.api_base_url or "http://api:8080").rstrip("/")
    url = f"{base_url}{path.format(job_id=job_id)}"
    timeout = httpx.Timeout(10.0, connect=3.0)
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, json=payload)
        response.raise_for_status()


def _mark_job_started(*, job_id: str) -> None:
    worker_id = os.getenv("HOSTNAME") or os.getenv("RQ_WORKER_ID") or "freecad-worker"
    try:
        _post_internal_job_update(
            job_id=job_id,
            path="/internal/jobs/{job_id}/started",
            payload={"worker_id": worker_id},
        )
    except Exception as exc:
        print(f"WARN: failed to mark job started for {job_id}: {type(exc).__name__}: {exc}")


def _mark_job_complete(*, job_id: str, passed: bool, result: dict | None = None, error: dict | None = None) -> None:
    try:
        _post_internal_job_update(
            job_id=job_id,
            path="/internal/jobs/{job_id}/complete",
            payload={
                "status": "finished" if passed else "failed",
                "result": result,
                "error": error,
            },
        )
    except Exception as exc:
        print(f"WARN: failed to mark job complete for {job_id}: {type(exc).__name__}: {exc}")

def _freecad_artifact_kind(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix == ".fcstd":
        return "freecad_model_fcstd"
    if suffix == ".step":
        return "cad_model_step"
    if suffix == ".stl":
        return "cad_model_stl"
    return None


def _resolve_freecadcmd() -> str | None:
    for candidate in (
        os.getenv("FREECADCMD"),
        os.getenv("FREECAD_CMD"),
        "freecadcmd",
        "FreeCADCmd",
    ):
        if not candidate:
            continue
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def _upload_generated_model_artifacts(*, outdir: Path, session_id: str, user_message_id: str) -> list[dict]:
    artifacts: list[dict] = []
    preferred_names = [outdir / "model.FCStd", outdir / "model.step", outdir / "model.stl"]
    discovered: list[Path] = []
    seen: set[Path] = set()

    for path in preferred_names:
        if path.exists() and path.is_file() and path not in seen:
            discovered.append(path)
            seen.add(path)

    for pattern in ("*.FCStd", "*.fcstd", "*.step", "*.stp", "*.stl"):
        for path in sorted(outdir.glob(pattern)):
            if path.is_file() and path not in seen:
                discovered.append(path)
                seen.add(path)

    suffix_counters: dict[str, int] = {}
    for path in discovered:
        kind = _freecad_artifact_kind(path)
        if not kind:
            # normalize .stp to the step kind and extension if present
            if path.suffix.lower() == ".stp":
                kind = "cad_model_step"
            else:
                continue
        canonical_suffix = ".step" if path.suffix.lower() == ".stp" else path.suffix
        index = suffix_counters.get(canonical_suffix, 0)
        suffix_counters[canonical_suffix] = index + 1
        stem = user_message_id if index == 0 else f"{user_message_id}.{index}"
        object_key = f"sessions/{session_id}/models/{stem}{canonical_suffix}"
        artifacts.append(_put_artifact(key=object_key, data=path.read_bytes(), kind=kind))
    return artifacts


def _llm_runtime_budget(timeout_seconds: int, *, prompt_tokens: int = 0, ctx_size: int | None = None) -> dict[str, int | float | None]:
    """Derive a context-aware runtime budget without imposing an application-side token cap."""
    total = max(60, int(timeout_seconds or 300))
    reserved_for_cleanup = min(120, max(30, total // 8))
    request_timeout = max(30, total - reserved_for_cleanup)
    ctx_value = int(ctx_size or settings.llm_ctx_size or 4096)
    reserve_tokens = int(getattr(settings, "llm_ctx_reserve_tokens", 256) or 256)
    prompt_value = max(0, int(prompt_tokens or 0))
    available_completion_tokens = max(1, ctx_value - prompt_value - reserve_tokens)
    return {
        "timeout_s": float(request_timeout),
        "max_attempts": 1,
        "ctx_size": ctx_value,
        "prompt_tokens": prompt_value,
        "available_completion_tokens": available_completion_tokens,
        "cap_reason": "context_window",
    }


def _python_syntax_error(source: str) -> str | None:
    try:
        compile(source, "<freecad-macro>", "exec")
        return None
    except SyntaxError as exc:
        line = (exc.text or "").strip()
        location = f"line {exc.lineno}" if exc.lineno else "unknown line"
        detail = exc.msg or "invalid syntax"
        if line:
            return f"{detail} at {location}: {line}"
        return f"{detail} at {location}"


def _macro_validation_error(source: str) -> str | None:
    patterns = [
        (r"(?m)\bFreeCAD\.export\s*\(", "FreeCAD.export is not a valid export API here; do not export from the macro"),
        (r"(?m)\bApp\.export\s*\(", "App.export is not a valid export API here; do not export from the macro"),
        (r"(?m)\bFreeCAD\.saveDocument\s*\(", "FreeCAD.saveDocument must not be used in generated macros"),
        (r"(?m)\bApp\.saveDocument\s*\(", "App.saveDocument must not be used in generated macros"),
        (r"(?m)\bdoc\.saveAs\s*\(", "doc.saveAs must not be used in generated macros"),
        (r"(?m)\bImport\.export\s*\(", "Import.export must not be used in generated macros"),
        (r"(?m)\bMesh\.export\s*\(", "Mesh.export must not be used in generated macros"),
    ]
    for pattern, message in patterns:
        if re.search(pattern, source or ""):
            return message
    return None


def _is_probably_truncated_syntax_issue(syntax_error: str) -> bool:
    lowered = (syntax_error or "").lower()
    return any(token in lowered for token in ("was never closed", "unterminated", "unexpected eof", "eof while scanning"))


def _looks_like_incomplete_python_prefix(candidate: str) -> bool:
    stripped = (candidate or "").strip()
    if not stripped:
        return False
    last = stripped.splitlines()[-1].strip()
    incomplete_prefixes = {"import", "from", "def", "class", "if", "elif", "for", "while", "with", "try", "except", "finally", "return", "yield", "async", "await"}
    return len(stripped) <= 32 and last in incomplete_prefixes


def _is_probable_truncation(candidate: str, syntax_error: str) -> bool:
    if _looks_like_incomplete_python_prefix(candidate):
        return True
    if _is_probably_truncated_syntax_issue(syntax_error):
        return len(candidate) >= 2000 or candidate.count("\n") >= 40
    lowered = (syntax_error or "").lower()
    return "invalid syntax" in lowered and len((candidate or "").strip()) <= 64


def _compact_retry_prompt_for_truncation(prompt: str, units: str | None, tolerance_mm: float | None) -> str:
    return build_compact_retry_prompt(prompt, "'(' was never closed", units or "mm", tolerance_mm if tolerance_mm is not None else 0.1)[1]["content"]


def _repair_prompt_for_invalid_python(candidate: str, syntax_error: str) -> str:
    return (
        f"The previous macro was not valid Python: {syntax_error}. "
        "Return a repaired, complete FreeCAD macro. Output ONLY valid Python code. "
        "Do not include markdown fences or explanations.\n\n"
        "Previous macro:\n"
        f"{candidate}"
    )


def _repair_prompt_for_failed_execution(candidate: str, failure: str) -> str:
    return (
        "The previous macro failed during headless FreeCAD execution. "
        "Return a repaired, complete FreeCAD macro. Output ONLY valid Python code. "
        "Do not include markdown fences or explanations.\n\n"
        f"Failure: {failure}\n\n"
        "Previous macro:\n"
        f"{candidate}"
    )


def _repair_prompt_for_nonzero_exit(candidate: str, stdout: str, stderr: str) -> str:
    return (
        "The previous macro exited with a non-zero status in headless FreeCAD. "
        "Return a repaired, complete FreeCAD macro. Output ONLY valid Python code. "
        "Do not include markdown fences or explanations.\n\n"
        f"STDOUT:\n{stdout[:2000]}\n\n"
        f"STDERR:\n{stderr[:2000]}\n\n"
        "Previous macro:\n"
        f"{candidate}"
    )


def _repair_prompt_for_missing_artifacts(candidate: str, stdout: str, stderr: str) -> str:
    return (
        "The previous macro ran in headless FreeCAD but did not create any exported model files. "
        "Return a repaired, complete FreeCAD macro that leaves exportable objects in the active document. "
        "Output ONLY valid Python code. Do not include markdown fences or explanations.\n\n"
        f"STDOUT:\n{stdout[:2000]}\n\n"
        f"STDERR:\n{stderr[:2000]}\n\n"
        "Previous macro:\n"
        f"{candidate}"
    )


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

    _mark_job_started(job_id=job_id)

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
    model_export_attempted = False
    model_export_skipped_reason: str | None = None
    model_export_returncode: int | None = None
    model_export_stdout = ""
    model_export_stderr = ""
    exported_model_object_keys: list[str] = []
    generation_attempts: list[dict] = []
    probable_truncation = False

    def _estimate_prompt_tokens(current_messages: list[dict[str, str]]) -> int:
        total_chars = sum(len(str(m.get("content", ""))) for m in current_messages)
        return max(1, total_chars // 4)

    estimated_prompt_tokens = _estimate_prompt_tokens(messages)
    llm_budget = _llm_runtime_budget(timeout_seconds, prompt_tokens=estimated_prompt_tokens)
    prompt_compacted = False
    if int(llm_budget["available_completion_tokens"]) < 256:
        messages = build_compact_generate_prompt(prompt, mode or "design", units or "mm", tolerance_mm if tolerance_mm is not None else 0.1)
        estimated_prompt_tokens = _estimate_prompt_tokens(messages)
        llm_budget = _llm_runtime_budget(timeout_seconds, prompt_tokens=estimated_prompt_tokens)
        prompt_compacted = True

    max_iterations = max(1, int(max_repair_iterations or 1))

    macro_code = ""
    raw_macro_code = ""
    successful_iteration: int | None = None
    freecadcmd = _resolve_freecadcmd()

    for iteration in range(1, max_iterations + 1):
        try:
            candidate = chat(
                messages,
                timeout_s=float(llm_budget["timeout_s"]),
                max_attempts=int(llm_budget["max_attempts"]),
                stop=["<|im_end|>", "</s>", "<|endoftext|>"],
            )
        except Exception as exc:
            placeholder_reason = f"llm request failed: {type(exc).__name__}: {exc}"
            issues.append(placeholder_reason)
            generation_attempts.append(
                {
                    "iteration": iteration,
                    "status": "llm_error",
                    "detail": placeholder_reason,
                }
            )
            break

        raw_macro_code = candidate if isinstance(candidate, str) else ""
        candidate = _normalize_generated_text(raw_macro_code)

        if not candidate.strip():
            placeholder_reason = "llm returned an empty response"
            issues.append(placeholder_reason)
            generation_attempts.append(
                {
                    "iteration": iteration,
                    "status": "empty_response",
                    "detail": placeholder_reason,
                }
            )
            break

        syntax_error = _python_syntax_error(candidate)
        if syntax_error:
            generation_attempts.append(
                {
                    "iteration": iteration,
                    "status": "invalid_python",
                    "detail": syntax_error,
                    "chars": len(candidate),
                }
            )
            macro_code = candidate
            model_export_skipped_reason = "generated macro is not valid Python"
            print(json.dumps({"status": "retrying", "retry-count": iteration, "reason": syntax_error}))
            if iteration >= max_iterations:
                issues.append(f"generated macro is not valid Python after {iteration} attempt(s): {syntax_error}")
                break
            if _is_probable_truncation(candidate, syntax_error):
                probable_truncation = True
                retry_prompt = _compact_retry_prompt_for_truncation(prompt, units, tolerance_mm)
            else:
                retry_prompt = _repair_prompt_for_invalid_python(candidate, syntax_error)
            messages = [messages[0], {"role": "user", "content": retry_prompt}]
            continue

        validation_error = _macro_validation_error(candidate)
        if validation_error:
            generation_attempts.append(
                {
                    "iteration": iteration,
                    "status": "invalid_macro_semantics",
                    "detail": validation_error,
                    "chars": len(candidate),
                }
            )
            macro_code = candidate
            model_export_skipped_reason = validation_error
            print(json.dumps({"status": "retrying", "retry-count": iteration, "reason": validation_error}))
            if iteration >= max_iterations:
                issues.append(f"generated macro failed validation after {iteration} attempt(s): {validation_error}")
                break
            semantic_failure = (
                "The previous macro failed validation before execution. "
                "The worker performs FCStd/STEP/STL export after the macro finishes, so the macro must not call export or save APIs itself. "
                "Return a repaired, complete FreeCAD macro that only creates geometry and leaves exportable objects in the active document. "
                "Output ONLY valid Python code. Do not include markdown fences or explanations.\n\n"
                f"Validation failure: {validation_error}\n\n"
                "Previous macro:\n"
                f"{candidate}"
            )
            messages = [messages[0], {"role": "user", "content": semantic_failure}]
            continue

        macro_code = candidate

        if freecadcmd is None:
            model_export_skipped_reason = "freecadcmd not available in this runtime"
            generation_attempts.append(
                {
                    "iteration": iteration,
                    "status": "skipped_no_freecadcmd",
                    "chars": len(candidate),
                }
            )
            successful_iteration = iteration
            break

        if not any(export_flags.values()):
            model_export_skipped_reason = "all model export flags are disabled"
            generation_attempts.append(
                {
                    "iteration": iteration,
                    "status": "skipped_exports_disabled",
                    "chars": len(candidate),
                }
            )
            successful_iteration = iteration
            break

        model_export_attempted = True
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            macro_path = tmp_path / f"{user_message_id}.py"
            macro_path.write_text(candidate, encoding="utf-8")
            outdir = tmp_path / "out"
            outdir.mkdir(parents=True, exist_ok=True)

            try:
                stdout, stderr, returncode = _run_freecad_headless(
                    freecadcmd=freecadcmd,
                    macro_path=str(macro_path),
                    outdir=str(outdir),
                    export=export_flags,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as exc:
                model_export_skipped_reason = f"FreeCAD execution failed: {type(exc).__name__}: {exc}"
                generation_attempts.append(
                    {
                        "iteration": iteration,
                        "status": "freecad_exception",
                        "detail": model_export_skipped_reason,
                        "chars": len(candidate),
                    }
                )
                if iteration >= max_iterations:
                    issues.append(model_export_skipped_reason)
                    break
                print(json.dumps({"status": "retrying", "retry-count": iteration, "reason": model_export_skipped_reason}))
                messages = [messages[0], {"role": "user", "content": _repair_prompt_for_failed_execution(candidate, model_export_skipped_reason)}]
                continue

            model_export_stdout = stdout or ""
            model_export_stderr = stderr or ""
            model_export_returncode = int(returncode)
            if model_export_returncode != 0:
                model_export_skipped_reason = f"FreeCAD exited with status {model_export_returncode}"
                generation_attempts.append(
                    {
                        "iteration": iteration,
                        "status": "freecad_nonzero_exit",
                        "detail": model_export_skipped_reason,
                        "chars": len(candidate),
                    }
                )
                if iteration >= max_iterations:
                    issues.append(model_export_skipped_reason)
                    break
                print(json.dumps({"status": "retrying", "retry-count": iteration, "reason": model_export_skipped_reason}))
                messages = [messages[0], {"role": "user", "content": _repair_prompt_for_nonzero_exit(candidate, model_export_stdout, model_export_stderr)}]
                continue

            model_artifacts = _upload_generated_model_artifacts(
                outdir=outdir,
                session_id=session_id,
                user_message_id=user_message_id,
            )
            if model_artifacts:
                artifacts.extend(model_artifacts)
                exported_model_object_keys = [a["object_key"] for a in model_artifacts]
                generation_attempts.append(
                    {
                        "iteration": iteration,
                        "status": "exported_models",
                        "chars": len(candidate),
                        "exported_model_object_keys": exported_model_object_keys,
                    }
                )
                successful_iteration = iteration
                model_export_skipped_reason = None
                break

            model_export_skipped_reason = "FreeCAD completed but did not produce any model artifacts"
            generation_attempts.append(
                {
                    "iteration": iteration,
                    "status": "no_model_artifacts",
                    "detail": model_export_skipped_reason,
                    "chars": len(candidate),
                }
            )
            if iteration >= max_iterations:
                issues.append(model_export_skipped_reason)
                break
            no_artifact_failure = _repair_prompt_for_missing_artifacts(candidate, model_export_stdout, model_export_stderr)
            print(json.dumps({"status": "retrying", "retry-count": iteration, "reason": model_export_skipped_reason}))
            messages = [messages[0], {"role": "user", "content": no_artifact_failure}]

    if placeholder_reason and not macro_code.strip():
        macro_code = (
            "# Generated macro was empty; writing a safe placeholder.\n"
            "import FreeCAD as App\n"
            "App.newDocument('Model')\n"
        )

    macro_bytes = macro_code.encode("utf-8")
    macro_key = f"sessions/{session_id}/macros/{user_message_id}.gen0.py"
    artifacts.insert(0, _put_artifact(key=macro_key, data=macro_bytes, kind="freecad_macro_py", content_type="text/x-python"))

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
        "initial_prompt_compacted": prompt_compacted,
        "placeholder_used": bool(placeholder_reason),
        "placeholder_reason": placeholder_reason,
        "raw_macro_chars": len(raw_macro_code),
        "generated_macro_chars": len(macro_code),
        "issues": issues,
        "generation_attempts": len(generation_attempts),
        "generation_attempt_details": generation_attempts,
        "successful_iteration": successful_iteration,
        "status": generation_attempts[-1]["status"] if generation_attempts else "not_started",
        "model_export_attempted": model_export_attempted,
        "model_export_skipped_reason": model_export_skipped_reason,
        "model_export_returncode": model_export_returncode,
        "model_export_stdout": model_export_stdout[:4000],
        "model_export_stderr": model_export_stderr[:4000],
        "exported_model_object_keys": exported_model_object_keys,
        "probable_truncation": probable_truncation,
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

    result = {
        "job_id": job_id,
        "session_id": session_id,
        "user_message_id": user_message_id,
        "passed": not bool(issues),
        "iterations": len(generation_attempts) or 1,
        "issues": issues,
        "artifacts": artifacts,
    }

    error = None
    if not result["passed"]:
        error = {
            "issues": issues,
        }

    _mark_job_complete(job_id=job_id, passed=result["passed"], result=result, error=error)
    return result


def _runner_script() -> str:
    return r"""
import os, traceback
import FreeCAD as App
import Part


def _non_null_shape(value):
    try:
        shape = getattr(value, "Shape", value)
        if isinstance(shape, Part.Shape) and not shape.isNull():
            return shape
    except Exception:
        return None
    return None


def _all_documents():
    try:
        docs = list(App.listDocuments().values())
    except Exception:
        docs = []
    active = getattr(App, "ActiveDocument", None)
    ordered = []
    seen = set()
    if active is not None:
        ordered.append(active)
        seen.add(getattr(active, "Name", id(active)))
    for doc in docs:
        key = getattr(doc, "Name", id(doc))
        if key in seen:
            continue
        ordered.append(doc)
        seen.add(key)
    return ordered


def _collect_shapes_from_documents():
    collected = []
    seen = set()
    for doc in _all_documents():
        try:
            objects = list(getattr(doc, "Objects", []))
        except Exception:
            objects = []
        for obj in objects:
            shape = _non_null_shape(obj)
            if shape is None:
                continue
            try:
                sig = shape.hashCode()
            except Exception:
                sig = id(shape)
            if sig in seen:
                continue
            seen.add(sig)
            collected.append((getattr(obj, "Name", "Result"), shape))
    return collected, seen


def _collect_shapes_from_globals(g, seen):
    collected = []
    for name, value in sorted(g.items()):
        if name.startswith("__"):
            continue
        shape = _non_null_shape(value)
        if shape is None:
            continue
        try:
            sig = shape.hashCode()
        except Exception:
            sig = id(shape)
        if sig in seen:
            continue
        seen.add(sig)
        collected.append((name, shape))
    return collected


def _collect_export_objects(g):
    doc_shapes, seen = _collect_shapes_from_documents()
    global_shapes = _collect_shapes_from_globals(g, seen)
    return doc_shapes + global_shapes


def _build_export_document(shape_items):
    try:
        existing = App.getDocument("ExportModel")
        if existing is not None:
            App.closeDocument(existing.Name)
    except Exception:
        pass
    doc = App.newDocument("ExportModel")
    export_objs = []
    for index, (name, shape) in enumerate(shape_items, start=1):
        label = name or f"Result{index}"
        safe_name = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in label) or f"Result{index}"
        feature = doc.addObject("Part::Feature", f"Recovered_{safe_name[:54]}")
        feature.Shape = shape.copy() if hasattr(shape, "copy") else shape
        export_objs.append(feature)
    try:
        doc.recompute()
    except Exception as e:
        print("VALIDATION:FREECAD_EXCEPTION:" + str(e))
    return doc, export_objs


def main():
    macro_path = os.environ.get("CAD_MACRO_PATH")
    outdir = os.environ.get("CAD_OUTDIR") or os.getcwd()
    export_fcstd = os.environ.get("CAD_EXPORT_FCSTD", "1")
    export_step = os.environ.get("CAD_EXPORT_STEP", "1")
    export_stl = os.environ.get("CAD_EXPORT_STL", "0")

    if not macro_path:
        raise RuntimeError("CAD_MACRO_PATH env var not set")

    os.makedirs(outdir, exist_ok=True)
    try:
        os.chdir(outdir)
    except Exception as e:
        print("VALIDATION:CHDIR_FAILED:" + str(e))

    g = {"App": App, "FreeCAD": App, "Part": Part}
    with open(macro_path, "r", encoding="utf-8") as f:
        code = f.read()
    try:
        exec(compile(code, macro_path, "exec"), g, g)
    except SystemExit as e:
        print("VALIDATION:EXEC_SYSTEM_EXIT:" + str(getattr(e, "code", 0)))

    for doc in _all_documents():
        try:
            doc.recompute()
        except Exception as e:
            print("VALIDATION:FREECAD_EXCEPTION:" + str(e))

    shape_items = _collect_export_objects(g)
    if not shape_items:
        print("VALIDATION:NO_EXPORTABLE_SHAPES")
        return

    doc, export_objs = _build_export_document(shape_items)
    base = os.path.join(outdir, "model")

    if export_fcstd == "1":
        try:
            doc.saveAs(base + ".FCStd")
        except Exception as e:
            print("VALIDATION:EXPORT_FAILED:FCSTD:" + str(e))
        else:
            if not (os.path.exists(base + ".FCStd") and os.path.getsize(base + ".FCStd") > 0):
                print("VALIDATION:EXPORT_FAILED:FCSTD:missing_output")

    if export_step == "1":
        try:
            import Import
            Import.export(export_objs, base + ".step")
            if not (os.path.exists(base + ".step") and os.path.getsize(base + ".step") > 0):
                print("VALIDATION:EXPORT_FAILED:STEP:missing_output")
        except Exception as e:
            print("VALIDATION:EXPORT_FAILED:STEP:" + str(e))

    if export_stl == "1":
        try:
            import Mesh
            Mesh.export(export_objs, base + ".stl")
            if not (os.path.exists(base + ".stl") and os.path.getsize(base + ".stl") > 0):
                print("VALIDATION:EXPORT_FAILED:STL:missing_output")
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

        cmd = [freecadcmd, str(runner_path)]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds, env=env)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("FreeCAD execution timed out") from exc

        return p.stdout, p.stderr, p.returncode


def main():
    raise SystemExit("worker.jobs.main is not intended to be called directly")
