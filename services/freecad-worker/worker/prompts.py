from __future__ import annotations
from typing import Any

SYSTEM = """You are a CAD assistant for FreeCAD.
You must produce deterministic, manufacturable CAD output.

Rules:
- Output MUST be a single Python script that can run in FreeCAD (macro).
- Do not include markdown fences.
- Prefer fully-constrained sketches when possible.
- Use millimeters by default unless told otherwise.
- Avoid unnecessary constraints and avoid redundant constraints.
- Always create or reuse a FreeCAD document.
- The worker handles FCStd, STEP, and STL export after your macro finishes.
- Do not call FreeCAD.saveDocument, App.saveDocument, Import.export, Mesh.export, or doc.saveAs in the generated macro.
- Leave one or more final exportable shape objects in the active document instead.
- Use `import FreeCAD as App` and refer to the active document through `App.ActiveDocument` or a local `doc` variable.
- Avoid assigning the result of `shape.translate(...)` or similar mutating methods because they usually return `None`; copy the shape first, then mutate the copy.
- When creating a Part::Feature, call `obj = doc.addObject("Part::Feature", "Result")` and then assign `obj.Shape = shape`; do not pass the shape as an extra argument to `addObject` and do not assign document properties like `Name` on raw Part shapes.
"""


def _truncate_middle(text: str, limit: int) -> str:
    value = str(text or "").strip()
    if limit <= 0 or len(value) <= limit:
        return value
    head = max(1, limit // 2 - 20)
    tail = max(1, limit - head - 21)
    return value[:head] + "\n...<snip>...\n" + value[-tail:]


def build_generate_prompt(user_prompt: str, mode: str, units: str, tolerance_mm: float) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"""Task mode: {mode}
Units: {units}
Tolerance (mm): {tolerance_mm}

User request:
{user_prompt}

Return: ONLY the FreeCAD Python macro code."""},
    ]


def build_repair_prompt(user_prompt: str, macro_code: str, issues: list[dict[str, Any]], units: str, tolerance_mm: float) -> list[dict[str, str]]:
    issue_lines = []
    for it in issues:
        issue_lines.append(f"- rule_code={it.get('rule_code')} object={it.get('object_name')} message={it.get('message')}")
    issues_block = "\n".join(issue_lines) if issue_lines else "(none)"
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"""You previously generated this FreeCAD macro, but validation failed because it is not valid Python or did not pass validation.

Original request:
{user_prompt}

Validation issues:
{issues_block}

Current macro:
{macro_code}

Fix the macro so that it runs headless in FreeCAD and resolves the issues above.
Return: ONLY the corrected FreeCAD Python macro code."""},
    ]


def build_compact_retry_prompt(user_prompt: str, issue_message: str, units: str, tolerance_mm: float) -> list[dict[str, str]]:
    compact_request = _truncate_middle(user_prompt, 2400)
    compact_issue = _truncate_middle(issue_message, 600)
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"""The previous FreeCAD macro appears to have been truncated before completion.

Original request:
{compact_request}

Latest failure:
{compact_issue}

Generate a NEW FreeCAD macro from scratch that satisfies the request with the simplest reliable geometry possible.
Keep the macro concise.
Do not repeat lines or add filler code.
Return: ONLY the FreeCAD Python macro code."""},
    ]


def build_compact_generate_prompt(user_prompt: str, mode: str, units: str, tolerance_mm: float) -> list[dict[str, str]]:
    compact_request = _truncate_middle(user_prompt, 2400)
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"""Task mode: {mode}
Units: {units}
Tolerance (mm): {tolerance_mm}

User request:
{compact_request}

Generate a NEW FreeCAD macro from scratch that satisfies the request with the simplest reliable geometry possible.
Keep the macro concise.
Do not repeat lines or add filler code.
Return: ONLY the FreeCAD Python macro code."""},
    ]
