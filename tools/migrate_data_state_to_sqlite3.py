#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_DIR = Path("./data/llm/state")
DB_PATH = STATE_DIR / "llm-state.sqlite3"
LATEST_POINTER_PATH = STATE_DIR / "latest.json"

REQUIRED_JSON_FILES = {
    "manifest_json": "manifest.json",
    "checkpoint_json": "checkpoint.json",
    "optimizer_state_json": "optimizer_state.json",
    "weights_json": "weights.json",
    "lora_adapter_json": "lora_adapter.json",
    "embedding_index_json": "embedding_index.json",
}
OPTIONAL_JSON_FILES = {
    "inference_profile_json": "inference_profile.json",
}


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def json_dumps(payload: dict[str, Any] | list[Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def utc_iso_from_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def ensure_schema(conn: sqlite3.Connection) -> None:
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


def build_sqlite_manifest_paths(run_id: str, db_path: Path) -> dict[str, str]:
    db_uri = f"sqlite://{db_path}"
    return {
        "checkpoint": f"{db_uri}#run_id={run_id}&field=checkpoint_json",
        "weights": f"{db_uri}#run_id={run_id}&field=weights_json",
        "lora_adapter": f"{db_uri}#run_id={run_id}&field=lora_adapter_json",
        "optimizer_state": f"{db_uri}#run_id={run_id}&field=optimizer_state_json",
        "embedding_index": f"{db_uri}#run_id={run_id}&field=embedding_index_json",
        "inference_profile": f"{db_uri}#run_id={run_id}&field=inference_profile_json",
    }


def choose_created_at(
    run_dir: Path,
    manifest: dict[str, Any],
    inference_profile: dict[str, Any] | None,
    latest_pointer: dict[str, Any] | None,
) -> str:
    if inference_profile and isinstance(inference_profile.get("created_at"), str) and inference_profile["created_at"].strip():
        return inference_profile["created_at"].strip()

    if latest_pointer and latest_pointer.get("run_id") == manifest.get("run_id"):
        updated_at = latest_pointer.get("updated_at")
        if isinstance(updated_at, str) and updated_at.strip():
            return updated_at.strip()

    return utc_iso_from_mtime(run_dir / "manifest.json")


def migrate_run(
    conn: sqlite3.Connection,
    run_dir: Path,
    db_path: Path,
    latest_pointer: dict[str, Any] | None,
) -> tuple[str, str]:
    loaded: dict[str, Any] = {}

    for column_name, filename in REQUIRED_JSON_FILES.items():
        file_path = run_dir / filename
        if not file_path.exists():
            raise FileNotFoundError(f"Missing required file: {file_path}")
        loaded[column_name] = read_json(file_path)

    for column_name, filename in OPTIONAL_JSON_FILES.items():
        file_path = run_dir / filename
        loaded[column_name] = read_json(file_path) if file_path.exists() else None

    manifest = dict(loaded["manifest_json"])
    run_id = str(manifest.get("run_id") or run_dir.name).strip()
    if not run_id:
        raise ValueError(f"Could not determine run_id for {run_dir}")

    manifest["run_id"] = run_id
    manifest["paths"] = build_sqlite_manifest_paths(run_id=run_id, db_path=db_path)

    inference_profile = loaded["inference_profile_json"]
    created_at = choose_created_at(
        run_dir=run_dir,
        manifest=manifest,
        inference_profile=inference_profile,
        latest_pointer=latest_pointer,
    )

    conn.execute(
        """
        INSERT INTO state_runs (
            run_id,
            created_at,
            manifest_json,
            inference_profile_json,
            checkpoint_json,
            optimizer_state_json,
            weights_json,
            lora_adapter_json,
            embedding_index_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id) DO UPDATE SET
            created_at = excluded.created_at,
            manifest_json = excluded.manifest_json,
            inference_profile_json = excluded.inference_profile_json,
            checkpoint_json = excluded.checkpoint_json,
            optimizer_state_json = excluded.optimizer_state_json,
            weights_json = excluded.weights_json,
            lora_adapter_json = excluded.lora_adapter_json,
            embedding_index_json = excluded.embedding_index_json
        """,
        (
            run_id,
            created_at,
            json_dumps(manifest),
            json_dumps(inference_profile) if inference_profile is not None else None,
            json_dumps(loaded["checkpoint_json"]),
            json_dumps(loaded["optimizer_state_json"]),
            json_dumps(loaded["weights_json"]),
            json_dumps(loaded["lora_adapter_json"]),
            json_dumps(loaded["embedding_index_json"]),
        ),
    )

    return run_id, created_at


def load_latest_pointer(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return read_json(path)


def pick_latest_run(conn: sqlite3.Connection) -> tuple[str, str, dict[str, Any]] | None:
    row = conn.execute(
        """
        SELECT run_id, created_at, manifest_json
        FROM state_runs
        ORDER BY created_at DESC, run_id DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    return str(row[0]), str(row[1]), json.loads(row[2])


def write_state_latest(conn: sqlite3.Connection, latest_pointer: dict[str, Any] | None) -> None:
    if latest_pointer and isinstance(latest_pointer.get("run_id"), str) and latest_pointer["run_id"].strip():
        run_id = latest_pointer["run_id"].strip()
        row = conn.execute(
            "SELECT manifest_json FROM state_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is not None:
            manifest = json.loads(row[0])
            updated_at = latest_pointer.get("updated_at")
            if not isinstance(updated_at, str) or not updated_at.strip():
                updated_at = datetime.now(timezone.utc).isoformat()
            model = latest_pointer.get("model")
            if not isinstance(model, dict):
                model = manifest.get("model", {}) if isinstance(manifest.get("model"), dict) else {}
            conn.execute(
                """
                INSERT INTO state_latest(singleton_id, run_id, updated_at, model_json)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    run_id = excluded.run_id,
                    updated_at = excluded.updated_at,
                    model_json = excluded.model_json
                """,
                (run_id, updated_at, json_dumps(model)),
            )
            return

    picked = pick_latest_run(conn)
    if picked is None:
        return

    run_id, created_at, manifest = picked
    model = manifest.get("model", {}) if isinstance(manifest.get("model"), dict) else {}
    conn.execute(
        """
        INSERT INTO state_latest(singleton_id, run_id, updated_at, model_json)
        VALUES (1, ?, ?, ?)
        ON CONFLICT(singleton_id) DO UPDATE SET
            run_id = excluded.run_id,
            updated_at = excluded.updated_at,
            model_json = excluded.model_json
        """,
        (run_id, created_at, json_dumps(model)),
    )


def main() -> None:
    if not STATE_DIR.exists():
        raise SystemExit(f"State directory does not exist: {STATE_DIR}")

    run_dirs = sorted(
        p for p in STATE_DIR.iterdir()
        if p.is_dir() and (p / "manifest.json").exists()
    )
    if not run_dirs:
        raise SystemExit(f"No legacy run directories found under: {STATE_DIR}")

    latest_pointer = load_latest_pointer(LATEST_POINTER_PATH)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    migrated = 0
    with sqlite3.connect(DB_PATH) as conn:
        ensure_schema(conn)

        for run_dir in run_dirs:
            migrate_run(
                conn=conn,
                run_dir=run_dir,
                db_path=DB_PATH,
                latest_pointer=latest_pointer,
            )
            migrated += 1

        write_state_latest(conn, latest_pointer)
        conn.commit()

        run_count = conn.execute("SELECT COUNT(*) FROM state_runs").fetchone()[0]
        latest_row = conn.execute(
            "SELECT run_id, updated_at FROM state_latest WHERE singleton_id = 1"
        ).fetchone()

    print(f"Migrated/updated {migrated} legacy run directories into {DB_PATH}")
    print(f"state_runs row count: {run_count}")
    if latest_row is not None:
        print(f"state_latest run_id: {latest_row[0]}")
        print(f"state_latest updated_at: {latest_row[1]}")
    else:
        print("state_latest row was not written")


if __name__ == "__main__":
    main()