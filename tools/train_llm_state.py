from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER_ROOT = REPO_ROOT / "services" / "freecad-worker"
if str(WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKER_ROOT))

from worker import model_state  # noqa: E402


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_text_documents(document_paths: list[str]) -> list[str]:
    documents: list[str] = []
    for raw in document_paths:
        path = Path(raw).expanduser().resolve()
        documents.append(path.read_text(encoding="utf-8"))
    return documents


def _hash_payload(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _build_checkpoint_payload(*, run_id: str, dataset: dict[str, Any], dataset_hash: str) -> dict[str, Any]:
    return {
        "format_version": 1,
        "run_id": run_id,
        "dataset_hash": dataset_hash,
        "epoch": int(dataset.get("epochs") or 1),
        "step": len(dataset.get("examples") or []),
        "status": "completed",
    }


def _build_weights_payload(*, dataset_hash: str, model: dict[str, Any], examples: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "format_version": 1,
        "base_model": model,
        "dataset_hash": dataset_hash,
        "example_count": len(examples),
        "parameter_strategy": "external-backend-managed",
        "notes": "This repository persists reusable training state and can also import externally produced binary weights.",
    }


def _build_lora_payload(*, examples: list[dict[str, Any]], model: dict[str, Any]) -> dict[str, Any]:
    style_tokens = sorted({token for item in examples for token in str(item.get("response") or "").split() if len(token) > 6})[:50]
    return {
        "format_version": 1,
        "adapter_type": "metadata-profile",
        "target_model": model,
        "style_tokens": style_tokens,
        "rank": min(max(len(style_tokens), 1), 16),
    }


def _build_optimizer_payload(*, dataset: dict[str, Any], dataset_hash: str) -> dict[str, Any]:
    return {
        "format_version": 1,
        "optimizer": dataset.get("optimizer") or {"name": "adamw", "learning_rate": 0.0001},
        "dataset_hash": dataset_hash,
        "completed_steps": len(dataset.get("examples") or []),
    }


def _build_embedding_index_payload(*, documents: list[str], dataset_hash: str) -> dict[str, Any]:
    snippets = [doc.strip().replace("\r\n", "\n")[:1200] for doc in documents if doc.strip()]
    return {
        "format_version": 1,
        "dataset_hash": dataset_hash,
        "document_count": len(snippets),
        "documents": [
            {
                "id": f"doc-{idx + 1}",
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "text": text,
            }
            for idx, text in enumerate(snippets)
        ],
    }


def train_and_persist(dataset_path: str, *, state_dir: str | None = None, run_id: str | None = None) -> model_state.StateSnapshot:
    dataset_file = Path(dataset_path).expanduser().resolve()
    dataset = _read_json(dataset_file)
    examples = list(dataset.get("examples") or [])
    document_paths = list(dataset.get("document_paths") or [])
    inline_documents = [str(item) for item in (dataset.get("documents") or [])]
    documents = _read_text_documents(document_paths) + inline_documents

    effective_run_id = run_id or model_state.utc_now_compact()
    model = dataset.get("model") or {
        "model_id": dataset.get("model_id") or "trained-freecad-profile",
        "backend": dataset.get("backend") or "llama.cpp",
        "device": dataset.get("device") or "cpu",
    }
    dataset_hash = _hash_payload(dataset)
    inference_profile = model_state.build_inference_profile(examples=examples, documents=documents, model=model)
    manifest = {
        "format_version": 1,
        "run_id": effective_run_id,
        "created_from": str(dataset_file),
        "dataset_hash": dataset_hash,
        "training_summary": {
            "examples": len(examples),
            "documents": len(documents),
        },
        "model": model,
    }
    imported_artifacts = {
        key: value
        for key, value in {
            "checkpoint": dataset.get("checkpoint_path"),
            "weights": dataset.get("weights_path"),
            "lora_adapter": dataset.get("lora_adapter_path"),
            "optimizer_state": dataset.get("optimizer_state_path"),
            "embedding_index": dataset.get("embedding_index_path"),
        }.items()
        if value
    }
    return model_state.persist_training_state(
        state_dir=state_dir,
        run_id=effective_run_id,
        manifest=manifest,
        inference_profile=inference_profile,
        checkpoint_payload=_build_checkpoint_payload(run_id=effective_run_id, dataset=dataset, dataset_hash=dataset_hash),
        optimizer_payload=_build_optimizer_payload(dataset=dataset, dataset_hash=dataset_hash),
        weights_payload=_build_weights_payload(dataset_hash=dataset_hash, model=model, examples=examples),
        lora_payload=_build_lora_payload(examples=examples, model=model),
        embedding_index_payload=_build_embedding_index_payload(documents=documents, dataset_hash=dataset_hash),
        imported_artifacts=imported_artifacts,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Persist reusable LLM training state for the FreeCAD AI stack.")
    parser.add_argument("--dataset", required=True, help="Path to a JSON dataset/config file.")
    parser.add_argument("--state-dir", default=None, help="Override the LLM state directory.")
    parser.add_argument("--run-id", default=None, help="Optional explicit run identifier.")
    args = parser.parse_args()

    snapshot = train_and_persist(args.dataset, state_dir=args.state_dir, run_id=args.run_id)
    print(
        json.dumps(
            {
                "run_id": snapshot.run_id,
                "state_path": str(snapshot.path),
                "latest_pointer": str(snapshot.path.parent / model_state.LATEST_POINTER_FILENAME),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
