import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from worker.llm import _normalize_generated_text, chat
from worker.prompts import build_compact_retry_prompt, build_generate_prompt, build_repair_prompt
from worker.storage import put_object
from worker.settings import settings


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
        ".step": "cad_model_step",
        ".stp": "cad_model_step",
        ".stl": "cad_model_stl",
    }.get(suffix, "freecad_model_file")


def _expected_model_kinds(export: dict[str, bool] | None = None) -> list[str]:
    export_flags = export or {"fcstd": True, "step": True, "stl": False}
    kinds: list[str] = []
    if export_flags.get("fcstd", True):
        kinds.append("freecad_model_fcstd")
    if export_flags.get("step", True):
        kinds.append("cad_model_step")
    if export_flags.get("stl", False):
        kinds.append("cad_model_stl")
    return kinds


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


def _estimate_message_tokens(messages: list[dict[str, str]]) -> int:
    total_chars = 0
    for message in messages or []:
        total_chars += len(str(message.get("role") or ""))
        total_chars += len(str(message.get("content") or ""))
    # Cheap conservative estimate for llama.cpp token budgeting.
    return max(1, total_chars // 4) + max(1, len(messages or [])) * 8


def _normalize_requested_max_tokens(llm_max_tokens: int | None) -> int | None:
    if llm_max_tokens in (None, ""):
        return None
    try:
        value = int(llm_max_tokens)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _llm_generation_budget(
    timeout_seconds: int,
    llm_max_tokens: int | None = None,
    *,
    prompt_tokens: int | None = None,
    ctx_size: int | None = None,
) -> dict[str, int | float | None | str]:
    """Keep the LLM call inside the enclosing RQ job timeout and context window."""
    total = max(60, int(timeout_seconds or 300))
    reserved_for_cleanup = min(180, max(45, total // 6))
    request_timeout = max(30, total - reserved_for_cleanup)

    context_window = max(1024, int(ctx_size or settings.llm_ctx_size or 4096))
    reserve_tokens = max(64, int(getattr(settings, "llm_ctx_reserve_tokens", 256) or 256))
    estimated_prompt_tokens = max(1, int(prompt_tokens or 0))
    available_completion_tokens = max(128, context_window - estimated_prompt_tokens - reserve_tokens)

    requested = _normalize_requested_max_tokens(llm_max_tokens)
    if requested is None:
        max_tokens = available_completion_tokens
        cap_reason = "context_window"
    else:
        max_tokens = min(requested, available_completion_tokens)
        cap_reason = "requested_max_tokens" if requested <= available_completion_tokens else "context_window"

    return {
        "timeout_s": float(request_timeout),
        "max_attempts": 1,
        "max_tokens": int(max_tokens),
        "requested_max_tokens": requested,
        "estimated_prompt_tokens": int(estimated_prompt_tokens),
        "available_completion_tokens": int(available_completion_tokens),
        "ctx_size": int(context_window),
        "reserve_tokens": int(reserve_tokens),
        "cap_reason": cap_reason,
    }


def _is_probably_truncated_syntax_issue(detail: str | None) -> bool:
    lowered = str(detail or "").lower()
    markers = (
        "was never closed",
        "unexpected eof",
        "unterminated string literal",
        "unterminated triple-quoted string literal",
        "eof while scanning",
    )
    return any(marker in lowered for marker in markers)


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


def _classify_runtime_issue(stderr: str) -> dict[str, str] | None:
    if not stderr.strip():
        return None
    for line in stderr.splitlines():
        stripped = line.strip()
        if not stripped or stripped == '>>>':
            continue
        lowered = stripped.lower()
        if 'AttributeError:' in stripped and 'saveDocument' in stripped:
            return {
                "rule_code": "forbidden_export_call",
                "object_name": "generated_macro",
                "message": "Do not call FreeCAD.saveDocument/App.saveDocument or perform exports inside the macro. Leave exportable objects in the active document and let the worker export them.",
            }
        if 'null shape' in lowered or 'validation:no_exportable_objects' in lowered:
            return {
                "rule_code": "null_or_nonexportable_shape",
                "object_name": "generated_macro",
                "message": "The macro created an object with a null or non-exportable shape. Ensure the final model creates real geometry and when using Part::Feature assign obj.Shape = shape after doc.addObject(...).",
            }
        if "has no attribute 'Name'" in stripped or 'has no attribute "Name"' in stripped:
            return {
                "rule_code": "runtime_execution_error",
                "object_name": "generated_macro",
                "message": "Do not assign document object properties like Name onto raw Part shapes. Create the shape first, then create a document object with doc.addObject('Part::Feature', 'Result') and assign obj.Shape = shape.",
            }
    tail = "\n".join([ln for ln in stderr.splitlines() if ln.strip()][-12:])
    return {
        "rule_code": "runtime_execution_error",
        "object_name": "generated_macro",
        "message": tail[:4000],
    }

def _runtime_repair_messages(
    *,
    prompt: str,
    macro_code: str,
    stderr: str,
    units: str | None,
    tolerance_mm: float | None,
) -> list[dict[str, str]]:
    issue = _classify_runtime_issue(stderr)
    issues = [issue] if issue else []
    return build_repair_prompt(
        prompt,
        macro_code,
        issues,
        units or "mm",
        tolerance_mm if tolerance_mm is not None else 0.1,
    )




def _upload_companion_fcmacro(*, session_id: str, user_message_id: str, macro_code: str) -> None:
    macro_bytes = macro_code.encode("utf-8")
    # FreeCAD's macro chooser expects .FCMacro files, so upload a companion copy
    # alongside the plain Python source for direct loading in the desktop UI.
    put_object(
        f"sessions/{session_id}/macros/{user_message_id}.FCMacro",
        macro_bytes,
        content_type="text/plain",
    )


def _missing_expected_model_kinds(model_artifacts: list[dict], export: dict[str, bool] | None = None) -> list[str]:
    produced = {str(a.get("kind")) for a in model_artifacts}
    return [kind for kind in _expected_model_kinds(export) if kind not in produced]


def _should_attempt_runtime_repair(
    *,
    returncode: int,
    stderr: str,
    model_artifacts: list[dict],
    export: dict[str, bool] | None = None,
) -> tuple[bool, dict[str, str] | None]:
    issue = _classify_runtime_issue(stderr)
    if issue is None:
        return False, None
    missing_expected = _missing_expected_model_kinds(model_artifacts, export)
    if returncode != 0 or not model_artifacts or bool(missing_expected):
        return True, issue
    return False, issue

def _generate_macro_with_repairs(
    *,
    prompt: str,
    mode: str | None,
    units: str | None,
    tolerance_mm: float | None,
    timeout_seconds: int,
    llm_max_tokens: int | None,
    max_repair_iterations: int,
) -> tuple[str, str, list[str], int, list[dict[str, object]], dict[str, object]]:
    issues: list[str] = []
    messages = _build_generation_messages(prompt, mode, units, tolerance_mm)
    last_macro = ""
    attempts = max(1, int(max_repair_iterations or 1))
    generation_attempts: list[dict[str, object]] = []
    final_budget: dict[str, object] = {}

    for iteration in range(1, attempts + 1):
        budget = _llm_generation_budget(
            timeout_seconds,
            llm_max_tokens,
            prompt_tokens=_estimate_message_tokens(messages),
        )
        final_budget = dict(budget)
        try:
            macro_code = chat(
                messages,
                timeout_s=float(budget["timeout_s"]),
                max_attempts=int(budget["max_attempts"]),
                max_tokens=int(budget["max_tokens"]),
                stop=["<|im_end|>", "</s>", "<|endoftext|>"],
            )
        except Exception as exc:
            reason = f"llm request failed: {type(exc).__name__}: {exc}"
            issues.append(reason)
            generation_attempts.append({
                "iteration": iteration,
                "status": "llm_error",
                "detail": reason[:500],
                "estimated_prompt_tokens": budget["estimated_prompt_tokens"],
                "max_tokens": budget["max_tokens"],
                "requested_max_tokens": budget["requested_max_tokens"],
                "ctx_size": budget["ctx_size"],
                "available_completion_tokens": budget["available_completion_tokens"],
            })
            return "", reason, issues, iteration, generation_attempts, final_budget

        raw_macro_code = macro_code if isinstance(macro_code, str) else ""
        raw_macro_code = _normalize_generated_text(raw_macro_code)
        last_macro = raw_macro_code
        if not raw_macro_code.strip():
            reason = "llm returned an empty response"
            issues.append(reason)
            generation_attempts.append({
                "iteration": iteration,
                "status": "empty_response",
                "chars": 0,
                "estimated_prompt_tokens": budget["estimated_prompt_tokens"],
                "max_tokens": budget["max_tokens"],
                "requested_max_tokens": budget["requested_max_tokens"],
                "ctx_size": budget["ctx_size"],
                "available_completion_tokens": budget["available_completion_tokens"],
            })
            return "", reason, issues, iteration, generation_attempts, final_budget

        syntax_issue = _compile_macro_or_error(raw_macro_code, f"generation_{iteration}.py")
        if syntax_issue is None:
            generation_attempts.append({
                "iteration": iteration,
                "status": "ok",
                "chars": len(raw_macro_code),
                "estimated_prompt_tokens": budget["estimated_prompt_tokens"],
                "max_tokens": budget["max_tokens"],
                "requested_max_tokens": budget["requested_max_tokens"],
                "ctx_size": budget["ctx_size"],
                "available_completion_tokens": budget["available_completion_tokens"],
            })
            return raw_macro_code, "", issues, iteration, generation_attempts, final_budget

        issues.append(syntax_issue)
        probable_truncation = _is_probably_truncated_syntax_issue(syntax_issue)
        use_compact_retry = probable_truncation and len(raw_macro_code) > 1000
        generation_attempts.append({
            "iteration": iteration,
            "status": "invalid_python",
            "detail": syntax_issue[:500],
            "probable_truncation": probable_truncation,
            "chars": len(raw_macro_code),
            "estimated_prompt_tokens": budget["estimated_prompt_tokens"],
            "max_tokens": budget["max_tokens"],
            "requested_max_tokens": budget["requested_max_tokens"],
            "ctx_size": budget["ctx_size"],
            "available_completion_tokens": budget["available_completion_tokens"],
        })
        if iteration >= attempts:
            final_reason = f"generated macro is not valid Python after {attempts} attempt(s): {syntax_issue.split(': ', 1)[-1]}"
            issues = [final_reason]
            return raw_macro_code, final_reason, issues, iteration, generation_attempts, final_budget

        if use_compact_retry:
            messages = build_compact_retry_prompt(
                prompt,
                syntax_issue,
                units or "mm",
                tolerance_mm if tolerance_mm is not None else 0.1,
            )
        else:
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

    return last_macro, "llm returned no usable macro", issues, attempts, generation_attempts, final_budget

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

    _mark_job_started(job_id=job_id, session_id=session_id, user_message_id=user_message_id)

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

    raw_macro_code, generation_reason, generation_issues, generation_attempts, generation_attempt_details, llm_budget = _generate_macro_with_repairs(
        prompt=prompt,
        mode=mode,
        units=units,
        tolerance_mm=tolerance_mm,
        timeout_seconds=timeout_seconds,
        llm_max_tokens=llm_max_tokens,
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
        freecadcmd = _resolve_freecadcmd()
        render_result["freecadcmd"] = freecadcmd
        if freecadcmd:
            attempt_limit = max(1, int(max_repair_iterations or 1))
            current_macro_code = macro_code
            current_raw_macro_code = raw_macro_code
            current_generation_attempts = generation_attempts
            for render_attempt in range(1, attempt_limit + 1):
                with tempfile.TemporaryDirectory() as tmpdir:
                    macro_path = Path(tmpdir) / f"{user_message_id}.py"
                    macro_path.write_text(current_macro_code, encoding="utf-8")
                    model_outdir = Path(tmpdir) / "models"
                    model_outdir.mkdir(parents=True, exist_ok=True)
                    try:
                        stdout, stderr, returncode = _run_freecad_headless(
                            freecadcmd=freecadcmd,
                            macro_path=str(macro_path),
                            outdir=str(model_outdir),
                            export=export_flags,
                            timeout_seconds=timeout_seconds,
                        )
                    except Exception as exc:
                        render_result["stderr"] = f"{type(exc).__name__}: {exc}"
                        issues.append(f"freecad execution failed: {type(exc).__name__}: {exc}")
                        break

                    runner_start_seen, runner_done_seen = _runner_markers(stdout, stderr)
                    model_artifacts = _collect_model_artifacts(
                        session_id=session_id,
                        user_message_id=user_message_id,
                        outdir=str(model_outdir),
                        export=export_flags,
                    )
                    render_result.update({
                        "executed": True,
                        "stdout": stdout,
                        "stderr": stderr,
                        "returncode": returncode,
                        "runner_start_seen": runner_start_seen,
                        "runner_done_seen": runner_done_seen,
                        "runner_markers_seen": runner_start_seen and runner_done_seen,
                        "uploaded_model_kinds": [artifact["kind"] for artifact in model_artifacts],
                    })

                    should_repair, runtime_issue = _should_attempt_runtime_repair(
                        returncode=returncode,
                        stderr=stderr,
                        model_artifacts=model_artifacts,
                        export=export_flags,
                    )
                    if should_repair and runtime_issue and render_attempt < attempt_limit:
                        repair_messages = _runtime_repair_messages(
                            prompt=prompt,
                            macro_code=current_macro_code,
                            stderr=stderr,
                            units=units,
                            tolerance_mm=tolerance_mm,
                        )
                        repair_budget = _llm_generation_budget(
                            timeout_seconds,
                            llm_max_tokens,
                            prompt_tokens=_estimate_message_tokens(repair_messages),
                        )
                        llm_budget = dict(repair_budget)
                        try:
                            repaired_macro = chat(
                                repair_messages,
                                timeout_s=float(repair_budget["timeout_s"]),
                                max_attempts=int(repair_budget["max_attempts"]),
                                max_tokens=int(repair_budget["max_tokens"]),
                                stop=["<|im_end|>", "</s>", "<|endoftext|>"],
                            )
                        except Exception as exc:
                            issues.append(f"llm request failed: {type(exc).__name__}: {exc}")
                            issues.append(f"freecad execution failed with return code {returncode}")
                            macro_code = current_macro_code
                            raw_macro_code = current_raw_macro_code
                            generation_attempts = current_generation_attempts
                            break
                        repaired_macro = repaired_macro if isinstance(repaired_macro, str) else ""
                        syntax_issue = _compile_macro_or_error(repaired_macro, f"runtime_repair_{render_attempt}.py") if repaired_macro.strip() else "llm returned an empty response"
                        if syntax_issue is None:
                            issues.append(runtime_issue["message"])
                            current_macro_code = repaired_macro
                            current_raw_macro_code = repaired_macro
                            current_generation_attempts += 1
                            continue
                        issues.append(runtime_issue["message"])
                        issues.append(syntax_issue)
                        current_generation_attempts += 1
                        placeholder_reason = syntax_issue
                        current_macro_code = (
                            "# Generated macro was empty; writing a safe placeholder.\n"
                            "import FreeCAD as App\n"
                            "App.newDocument('Model')\n"
                        )
                        macro_code = current_macro_code
                        raw_macro_code = current_raw_macro_code
                        break

                    artifacts.extend(model_artifacts)
                    if returncode != 0:
                        issues.append(f"freecad execution failed with return code {returncode}")
                    elif runner_start_seen and not runner_done_seen and not model_artifacts:
                        issues.append("freecad runner started but did not complete")
                    elif not runner_start_seen and not runner_done_seen and not model_artifacts:
                        issues.append("freecad process returned success but runner script did not execute")
                    if not model_artifacts:
                        issues.append("freecad execution completed but did not produce any model artifacts")
                    macro_code = current_macro_code
                    raw_macro_code = current_raw_macro_code
                    generation_attempts = current_generation_attempts
                    break
            else:
                generation_attempts = current_generation_attempts
        else:
            issues.append("freecadcmd not found; skipping model export")

    diag_status = "exported_models" if render_result.get("uploaded_model_kinds") else ("invalid_python" if placeholder_reason else "ok")

    model_export_skipped_reason = None
    if placeholder_reason and str(placeholder_reason).startswith("generated macro is not valid Python after"):
        model_export_skipped_reason = "generated macro is not valid Python"

    diag = {
        "status": diag_status,
        "successful_iteration": generation_attempts if not placeholder_reason else None,
        "model_export_skipped_reason": model_export_skipped_reason,
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
        "requested_llm_max_tokens": _normalize_requested_max_tokens(llm_max_tokens),
        "llm_budget": llm_budget,
        "generation_attempts": generation_attempts,
        "generation_attempt_details": generation_attempt_details,
        "iterations": generation_attempts,
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

    if placeholder_reason and not str(placeholder_reason).startswith("generated macro is not valid Python after"):
        reason_key = f"sessions/{session_id}/diagnostics/{user_message_id}.empty_macro_reason.txt"
        artifacts.append(
            _put_artifact(
                key=reason_key,
                data=(placeholder_reason + "\n").encode("utf-8"),
                kind="job_reason_txt",
                content_type="text/plain",
            )
        )

    _upload_companion_fcmacro(session_id=session_id, user_message_id=user_message_id, macro_code=macro_code)

    model_export_failed = bool(render_result.get("executed")) and not bool(render_result.get("uploaded_model_kinds"))
    passed = not bool(placeholder_reason) and not model_export_failed and not any(
        str(issue).startswith(("llm request failed", "generated macro is not valid Python after", "freecad execution failed"))
        for issue in issues
    )

    result = {
        "job_id": job_id,
        "session_id": session_id,
        "user_message_id": user_message_id,
        "passed": passed,
        "iterations": generation_attempts,
        "issues": issues,
        "artifacts": artifacts,
    }

    _mark_job_complete(
        job_id=job_id,
        session_id=session_id,
        user_message_id=user_message_id,
        passed=bool(result["passed"]),
        result=result if result["passed"] else None,
        error=None if result["passed"] else {"issues": issues, "artifacts": artifacts},
    )

    return result


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

    export_objs = [
        o for o in doc.Objects
        if hasattr(o, "Shape") and getattr(o, "Shape") is not None and not o.Shape.isNull()
    ]
    if not export_objs:
        print("VALIDATION:NO_EXPORTABLE_OBJECTS")

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

        try:
            p = subprocess.run(
                [freecadcmd, str(runner_path)],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("FreeCAD execution timed out") from exc

        return p.stdout, p.stderr, p.returncode


def _resolve_freecadcmd() -> str | None:
    return _detect_freecadcmd()


def _mark_job_started(*, job_id: str, session_id: str, user_message_id: str) -> None:
    try:
        import urllib.request
        data = json.dumps({
            "session_id": session_id,
            "user_message_id": user_message_id,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{settings.api_base_url.rstrip('/')}/internal/jobs/{job_id}/started",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception:
        return None


def _mark_job_complete(*, job_id: str, session_id: str, user_message_id: str, passed: bool, result: dict | None = None, error: dict | None = None) -> None:
    try:
        import urllib.request
        payload = {
            "session_id": session_id,
            "user_message_id": user_message_id,
            "passed": bool(passed),
            "result": result or {},
            "error": error or {},
        }
        req = urllib.request.Request(
            f"{settings.api_base_url.rstrip('/')}/internal/jobs/{job_id}/complete",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception:
        return None

def main():
    raise SystemExit("worker.jobs.main is not intended to be called directly")
