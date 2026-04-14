from __future__ import annotations

import json
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_LLM_STATE_DIR = "/data/llm/state"
LATEST_POINTER_FILENAME = "latest.json"
INFERENCE_PROFILE_FILENAME = "inference_profile.json"
SQLITE_DB_FILENAME = "llm-state.sqlite3"


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


def _db_path(state_dir: Path) -> Path:
    return state_dir / SQLITE_DB_FILENAME


def _connect(state_dir: Path) -> sqlite3.Connection:
    state_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_db_path(state_dir))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS state_runs (
            run_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            manifest_json TEXT NOT NULL,
            inference_profile_json TEXT,
            checkpoint_json TEXT NOT NULL,
            optimizer_state_json TEXT NOT NULL,
            weights_json TEXT NOT NULL,
            lora_adapter_json TEXT NOT NULL,
            embedding_index_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS state_imported_artifacts (
            run_id TEXT NOT NULL,
            artifact_name TEXT NOT NULL,
            artifact_filename TEXT NOT NULL,
            is_directory INTEGER NOT NULL DEFAULT 0,
            payload BLOB,
            PRIMARY KEY (run_id, artifact_name),
            FOREIGN KEY (run_id) REFERENCES state_runs(run_id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS state_latest (
            singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
            run_id TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            model_json TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES state_runs(run_id) ON DELETE CASCADE
        )
        """
    )
    return conn


def _json_dumps(payload: dict[str, Any] | list[Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def _json_loads(payload: str | bytes | bytearray | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8")
    return json.loads(payload)


def _legacy_latest_pointer_path(state_dir: Path) -> Path:
    return state_dir / LATEST_POINTER_FILENAME


def _legacy_read_latest_pointer(state_dir: Path) -> dict[str, Any] | None:
    pointer = _legacy_latest_pointer_path(state_dir)
    if not pointer.exists():
        return None
    return _read_json(pointer)


def _discover_run_id_from_directories(state_dir: Path) -> str | None:
    run_ids = [p.name for p in state_dir.iterdir() if p.is_dir() and (p / "manifest.json").exists()]
    return sorted(run_ids)[-1] if run_ids else None


def read_latest_pointer(state_dir: str | os.PathLike[str] | None = None) -> dict[str, Any] | None:
    state_dir_path = resolve_state_dir(state_dir)
    db_path = _db_path(state_dir_path)
    if db_path.exists():
        with _connect(state_dir_path) as conn:
            row = conn.execute(
                "SELECT run_id, updated_at, model_json FROM state_latest WHERE singleton_id = 1"
            ).fetchone()
        if row is not None:
            return {
                "run_id": str(row["run_id"]),
                "updated_at": str(row["updated_at"]),
                "manifest_path": f"sqlite://{db_path}#run_id={row['run_id']}",
                "inference_profile_path": f"sqlite://{db_path}#run_id={row['run_id']}",
                "model": _json_loads(row["model_json"]) or {},
            }
    return _legacy_read_latest_pointer(state_dir_path)


def write_latest_pointer(*, state_dir: str | os.PathLike[str] | None, run_id: str, manifest: dict[str, Any]) -> Path:
    state_dir_path = ensure_state_dir(state_dir)
    db_path = _db_path(state_dir_path)
    with _connect(state_dir_path) as conn:
        conn.execute(
            """
            INSERT INTO state_latest(singleton_id, run_id, updated_at, model_json)
            VALUES (1, ?, ?, ?)
            ON CONFLICT(singleton_id) DO UPDATE SET
                run_id = excluded.run_id,
                updated_at = excluded.updated_at,
                model_json = excluded.model_json
            """,
            (
                run_id,
                datetime.now(timezone.utc).isoformat(),
                _json_dumps(manifest.get("model", {})),
            ),
        )
        conn.commit()
    return db_path


def _load_snapshot_from_sqlite(state_dir_path: Path, run_id: str | None = None) -> StateSnapshot | None:
    db_path = _db_path(state_dir_path)
    if not db_path.exists():
        return None

    with _connect(state_dir_path) as conn:
        resolved_run_id = run_id
        if not resolved_run_id:
            row = conn.execute("SELECT run_id FROM state_latest WHERE singleton_id = 1").fetchone()
            resolved_run_id = str(row["run_id"]) if row is not None else None
        if not resolved_run_id:
            row = conn.execute("SELECT run_id FROM state_runs ORDER BY created_at DESC, run_id DESC LIMIT 1").fetchone()
            resolved_run_id = str(row["run_id"]) if row is not None else None
        if not resolved_run_id:
            return None

        row = conn.execute(
            "SELECT run_id, manifest_json, inference_profile_json FROM state_runs WHERE run_id = ?",
            (resolved_run_id,),
        ).fetchone()
    if row is None:
        return None

    return StateSnapshot(
        run_id=str(row["run_id"]),
        path=db_path,
        manifest=_json_loads(row["manifest_json"]) or {},
        inference_profile=_json_loads(row["inference_profile_json"]),
    )


def load_latest_snapshot(state_dir: str | os.PathLike[str] | None = None) -> StateSnapshot | None:
    state_dir_path = resolve_state_dir(state_dir)
    if not state_dir_path.exists():
        return None

    sqlite_snapshot = _load_snapshot_from_sqlite(state_dir_path)
    if sqlite_snapshot is not None:
        return sqlite_snapshot

    pointer = _legacy_read_latest_pointer(state_dir_path)
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
    db_path = _db_path(state_dir_path)

    manifest_with_paths = dict(manifest)
    manifest_with_paths["paths"] = {
        "checkpoint": f"sqlite://{db_path}#run_id={resolved_run_id}&field=checkpoint_json",
        "weights": f"sqlite://{db_path}#run_id={resolved_run_id}&field=weights_json",
        "lora_adapter": f"sqlite://{db_path}#run_id={resolved_run_id}&field=lora_adapter_json",
        "optimizer_state": f"sqlite://{db_path}#run_id={resolved_run_id}&field=optimizer_state_json",
        "embedding_index": f"sqlite://{db_path}#run_id={resolved_run_id}&field=embedding_index_json",
        "inference_profile": f"sqlite://{db_path}#run_id={resolved_run_id}&field=inference_profile_json",
    }

    copied: dict[str, str] = {}
    with _connect(state_dir_path) as conn:
        existing = conn.execute("SELECT 1 FROM state_runs WHERE run_id = ?", (resolved_run_id,)).fetchone()
        if existing is not None:
            raise ModelStateError(f"State run already exists: {resolved_run_id}")

        conn.execute(
            """
            INSERT INTO state_runs(
                run_id,
                created_at,
                manifest_json,
                inference_profile_json,
                checkpoint_json,
                optimizer_state_json,
                weights_json,
                lora_adapter_json,
                embedding_index_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resolved_run_id,
                datetime.now(timezone.utc).isoformat(),
                _json_dumps(manifest_with_paths),
                _json_dumps(inference_profile),
                _json_dumps(checkpoint_payload),
                _json_dumps(optimizer_payload),
                _json_dumps(weights_payload),
                _json_dumps(lora_payload),
                _json_dumps(embedding_index_payload),
            ),
        )

        for name, src in (imported_artifacts or {}).items():
            src_path = Path(src).expanduser().resolve()
            if not src_path.exists():
                raise ModelStateError(f"Imported artifact does not exist: {src_path}")
            if src_path.is_dir():
                raise ModelStateError(f"Imported artifact directories are not supported in sqlite state: {src_path}")
            target_name = f"imported_{name}{src_path.suffix}"
            conn.execute(
                """
                INSERT INTO state_imported_artifacts(run_id, artifact_name, artifact_filename, is_directory, payload)
                VALUES (?, ?, ?, 0, ?)
                """,
                (resolved_run_id, str(name), target_name, sqlite3.Binary(src_path.read_bytes())),
            )
            copied[name] = target_name

        if copied:
            manifest_with_paths["imported_artifacts"] = copied
            conn.execute(
                "UPDATE state_runs SET manifest_json = ? WHERE run_id = ?",
                (_json_dumps(manifest_with_paths), resolved_run_id),
            )

        conn.execute(
            """
            INSERT INTO state_latest(singleton_id, run_id, updated_at, model_json)
            VALUES (1, ?, ?, ?)
            ON CONFLICT(singleton_id) DO UPDATE SET
                run_id = excluded.run_id,
                updated_at = excluded.updated_at,
                model_json = excluded.model_json
            """,
            (
                resolved_run_id,
                datetime.now(timezone.utc).isoformat(),
                _json_dumps(manifest_with_paths.get("model", {})),
            ),
        )
        conn.commit()

    return StateSnapshot(run_id=resolved_run_id, path=db_path, manifest=manifest_with_paths, inference_profile=inference_profile)
