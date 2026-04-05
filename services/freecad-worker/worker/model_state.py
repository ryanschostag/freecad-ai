from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_LLM_STATE_DIR = "/data/llm/state"
LATEST_POINTER_FILENAME = "latest.json"
INFERENCE_PROFILE_FILENAME = "inference_profile.json"


@dataclass(frozen=True)
class StateSnapshot:
    run_id: str
    path: Path
    manifest: dict[str, Any]
    inference_profile: dict[str, Any] | None


class ModelStateError(RuntimeError):
    pass


def utc_now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def resolve_state_dir(value: str | os.PathLike[str] | None = None) -> Path:
    raw = value or os.getenv("LLM_STATE_DIR") or DEFAULT_LLM_STATE_DIR
    return Path(raw).expanduser().resolve()


def ensure_state_dir(path: str | os.PathLike[str] | None = None) -> Path:
    state_dir = resolve_state_dir(path)
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _latest_pointer_path(state_dir: Path) -> Path:
    return state_dir / LATEST_POINTER_FILENAME


def read_latest_pointer(state_dir: str | os.PathLike[str] | None = None) -> dict[str, Any] | None:
    state_dir_path = resolve_state_dir(state_dir)
    pointer = _latest_pointer_path(state_dir_path)
    if not pointer.exists():
        return None
    return _read_json(pointer)


def write_latest_pointer(*, state_dir: str | os.PathLike[str] | None, run_id: str, manifest: dict[str, Any]) -> Path:
    state_dir_path = ensure_state_dir(state_dir)
    pointer_payload = {
        "run_id": run_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_path": f"{run_id}/manifest.json",
        "inference_profile_path": f"{run_id}/{INFERENCE_PROFILE_FILENAME}",
        "model": manifest.get("model", {}),
    }
    pointer_path = _latest_pointer_path(state_dir_path)
    _write_json(pointer_path, pointer_payload)
    return pointer_path


def _discover_run_id_from_directories(state_dir: Path) -> str | None:
    run_ids = [p.name for p in state_dir.iterdir() if p.is_dir() and (p / "manifest.json").exists()]
    return sorted(run_ids)[-1] if run_ids else None


def load_latest_snapshot(state_dir: str | os.PathLike[str] | None = None) -> StateSnapshot | None:
    state_dir_path = resolve_state_dir(state_dir)
    if not state_dir_path.exists():
        return None

    pointer = read_latest_pointer(state_dir_path)
    run_id = pointer.get("run_id") if pointer else None
    if not run_id:
        run_id = _discover_run_id_from_directories(state_dir_path)
    if not run_id:
        return None

    run_dir = state_dir_path / str(run_id)
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        return None

    manifest = _read_json(manifest_path)
    inference_profile_path = run_dir / INFERENCE_PROFILE_FILENAME
    inference_profile = _read_json(inference_profile_path) if inference_profile_path.exists() else None
    return StateSnapshot(run_id=str(run_id), path=run_dir, manifest=manifest, inference_profile=inference_profile)


def build_inference_profile(*, examples: list[dict[str, Any]], documents: list[str], model: dict[str, Any]) -> dict[str, Any]:
    concise_examples: list[dict[str, str]] = []
    for item in examples[:20]:
        prompt = str(item.get("prompt") or item.get("input") or "").strip()
        response = str(item.get("response") or item.get("output") or "").strip()
        if prompt and response:
            concise_examples.append({"prompt": prompt, "response": response})

    snippets = [doc.strip() for doc in documents if str(doc).strip()][:20]
    system_lines = [
        "Use the persisted training profile when it is relevant.",
        "Favor the repository's established FreeCAD conventions and prior successful examples.",
    ]
    if concise_examples:
        system_lines.append("Relevant fine-tuning examples are attached in structured form.")
    if snippets:
        system_lines.append("Consult the persisted embedding snapshot snippets before answering when they match the request.")

    return {
        "format_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "system_message": " ".join(system_lines),
        "examples": concise_examples,
        "retrieval_snippets": snippets,
    }


def persist_training_state(
    *,
    state_dir: str | os.PathLike[str] | None,
    manifest: dict[str, Any],
    inference_profile: dict[str, Any],
    checkpoint_payload: dict[str, Any],
    optimizer_payload: dict[str, Any],
    weights_payload: dict[str, Any],
    lora_payload: dict[str, Any],
    embedding_index_payload: dict[str, Any],
    imported_artifacts: dict[str, str | os.PathLike[str]] | None = None,
    run_id: str | None = None,
) -> StateSnapshot:
    state_dir_path = ensure_state_dir(state_dir)
    resolved_run_id = run_id or utc_now_compact()
    run_dir = state_dir_path / resolved_run_id
    if run_dir.exists():
        raise ModelStateError(f"State run already exists: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=False)

    manifest_with_paths = dict(manifest)
    manifest_with_paths["paths"] = {
        "checkpoint": "checkpoint.json",
        "weights": "weights.json",
        "lora_adapter": "lora_adapter.json",
        "optimizer_state": "optimizer_state.json",
        "embedding_index": "embedding_index.json",
        "inference_profile": INFERENCE_PROFILE_FILENAME,
    }

    _write_json(run_dir / "manifest.json", manifest_with_paths)
    _write_json(run_dir / "checkpoint.json", checkpoint_payload)
    _write_json(run_dir / "weights.json", weights_payload)
    _write_json(run_dir / "lora_adapter.json", lora_payload)
    _write_json(run_dir / "optimizer_state.json", optimizer_payload)
    _write_json(run_dir / "embedding_index.json", embedding_index_payload)
    _write_json(run_dir / INFERENCE_PROFILE_FILENAME, inference_profile)

    copied: dict[str, str] = {}
    for name, src in (imported_artifacts or {}).items():
        src_path = Path(src).expanduser().resolve()
        if not src_path.exists():
            raise ModelStateError(f"Imported artifact does not exist: {src_path}")
        target_name = f"imported_{name}{src_path.suffix}" if src_path.is_file() else f"imported_{name}"
        target_path = run_dir / target_name
        if src_path.is_dir():
            shutil.copytree(src_path, target_path)
        else:
            shutil.copy2(src_path, target_path)
        copied[name] = target_path.name

    if copied:
        manifest_with_paths["imported_artifacts"] = copied
        _write_json(run_dir / "manifest.json", manifest_with_paths)

    write_latest_pointer(state_dir=state_dir_path, run_id=resolved_run_id, manifest=manifest_with_paths)
    return StateSnapshot(run_id=resolved_run_id, path=run_dir, manifest=manifest_with_paths, inference_profile=inference_profile)
