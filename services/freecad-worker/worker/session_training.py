from __future__ import annotations

import re

from worker import model_state


def _extract_lessons(*, previous_prompt: str, previous_macro: str, diagnostics_text: str, issues: list[str]) -> list[str]:
    lessons: list[str] = []
    combined = "\n".join([diagnostics_text, "\n".join(issues), previous_macro])

    if "isExportable" in combined:
        lessons.append(
            "Do not call doc.isExportable(...). FreeCAD documents do not provide that API in this stack. Leave final Part::Feature objects in the document and let the runner export them."
        )
    if re.search(r"\bdoc\.export\b", combined):
        lessons.append(
            "Do not call doc.export(...). The worker exports FCStd, STEP, and STL after the macro finishes."
        )
    if "Import.export" in combined:
        lessons.append(
            "Do not call Import.export(...) from the generated macro. The worker performs STEP export after the macro finishes."
        )
    if "Mesh.export" in combined:
        lessons.append(
            "Do not call Mesh.export(...) from the generated macro. The worker performs STL export after the macro finishes."
        )
    if "argument 3 must be Base.Vector" in combined:
        lessons.append(
            "When constructing Part geometry, pass FreeCAD.Vector instances instead of Python tuples wherever FreeCAD expects a Base.Vector."
        )
    if issues:
        lessons.append("Previous run issues to avoid:\n- " + "\n- ".join(str(item) for item in issues if str(item).strip()))
    if previous_macro.strip():
        lessons.append("Previous failing macro to avoid repeating verbatim:\n" + previous_macro.strip()[:4000])
    if previous_prompt.strip():
        lessons.append("This training snapshot was derived from the previous failed request in the same session:\n" + previous_prompt.strip()[:2000])
    return lessons


def build_session_training_snapshot(
    *,
    session_id: str,
    previous_job_id: str,
    previous_prompt: str,
    previous_macro_text: str,
    diagnostics_text: str,
    issues: list[str],
    state_dir: str | None = None,
) -> model_state.StateSnapshot:
    lessons = _extract_lessons(
        previous_prompt=previous_prompt,
        previous_macro=previous_macro_text,
        diagnostics_text=diagnostics_text,
        issues=issues,
    )
    examples: list[dict[str, str]] = []
    if previous_prompt.strip() and lessons:
        examples.append(
            {
                "prompt": previous_prompt.strip()[:2000],
                "response": "Avoid the previously-failing APIs and produce a headless-safe macro that leaves exportable Part::Feature objects in the document.",
            }
        )

    run_id = f"session-{session_id}-{previous_job_id}"
    manifest = {
        "format_version": 1,
        "run_id": run_id,
        "source": "session_failure_feedback",
        "session_id": session_id,
        "previous_job_id": previous_job_id,
        "training_summary": {"examples": len(examples), "documents": len(lessons)},
        "model": {"model_id": "session-feedback", "backend": "metadata-profile", "device": "cpu"},
    }
    inference_profile = model_state.build_inference_profile(
        examples=examples,
        documents=lessons,
        model=manifest["model"],
    )
    inference_profile["system_message"] = (
        "Use the session failure feedback when it is relevant. "
        "Do not repeat APIs or geometry patterns that failed earlier in this same session. "
        + str(inference_profile.get("system_message") or "")
    ).strip()

    return model_state.persist_training_state(
        state_dir=state_dir,
        run_id=run_id,
        manifest=manifest,
        inference_profile=inference_profile,
        checkpoint_payload={
            "format_version": 1,
            "run_id": run_id,
            "status": "completed",
            "source": "session_failure_feedback",
        },
        optimizer_payload={
            "format_version": 1,
            "optimizer": {"name": "session-feedback", "learning_rate": 0.0},
            "completed_steps": 1,
        },
        weights_payload={
            "format_version": 1,
            "parameter_strategy": "metadata-profile",
            "notes": "Session-derived negative feedback profile.",
        },
        lora_payload={
            "format_version": 1,
            "adapter_type": "metadata-profile",
            "lessons_count": len(lessons),
        },
        embedding_index_payload={
            "format_version": 1,
            "document_count": len(lessons),
            "documents": [
                {"id": f"lesson-{idx + 1}", "text": text}
                for idx, text in enumerate(lessons)
            ],
        },
    )
