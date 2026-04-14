import importlib.util
import sqlite3
import sys
from pathlib import Path


def _load_module(name: str, relative_path: str):
    repo_root = Path(__file__).resolve().parents[2]
    worker_root = repo_root / "services" / "freecad-worker"
    if str(worker_root) not in sys.path:
        sys.path.insert(0, str(worker_root))
    module_path = repo_root / relative_path
    spec = importlib.util.spec_from_file_location(name, module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)  # type: ignore[assignment]
    return module


def test_persist_training_state_writes_expected_sqlite_rows_and_latest_pointer(tmp_path):
    model_state = _load_module("worker_model_state_test", "services/freecad-worker/worker/model_state.py")

    snapshot = model_state.persist_training_state(
        state_dir=tmp_path,
        run_id="run-001",
        manifest={"model": {"model_id": "trained-freecad", "backend": "llama.cpp", "device": "cpu"}},
        inference_profile={"system_message": "use trained examples", "examples": [], "retrieval_snippets": []},
        checkpoint_payload={"step": 2},
        optimizer_payload={"optimizer": {"name": "adamw"}},
        weights_payload={"parameter_strategy": "external-backend-managed"},
        lora_payload={"adapter_type": "metadata-profile"},
        embedding_index_payload={"documents": []},
    )

    db_path = tmp_path / model_state.SQLITE_DB_FILENAME
    assert snapshot.path == db_path
    assert db_path.exists()

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT run_id, manifest_json, inference_profile_json, checkpoint_json FROM state_runs WHERE run_id = ?",
            ("run-001",),
        ).fetchone()
        latest = conn.execute("SELECT run_id FROM state_latest WHERE singleton_id = 1").fetchone()

    assert row is not None
    assert latest is not None
    assert latest[0] == "run-001"
    assert '"model_id": "trained-freecad"' in row[1]
    assert '"system_message": "use trained examples"' in row[2]
    assert '"step": 2' in row[3]


def test_load_latest_snapshot_falls_back_to_latest_run_directory(tmp_path):
    model_state = _load_module("worker_model_state_test_dirs", "services/freecad-worker/worker/model_state.py")

    for run_id in ("20260101T000000Z", "20260102T000000Z"):
        run_dir = tmp_path / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "manifest.json").write_text('{"run_id": "%s", "model": {}}' % run_id, encoding="utf-8")
        (run_dir / "inference_profile.json").write_text('{"system_message": "%s"}' % run_id, encoding="utf-8")

    snapshot = model_state.load_latest_snapshot(tmp_path)

    assert snapshot is not None
    assert snapshot.run_id == "20260102T000000Z"
    assert snapshot.inference_profile["system_message"] == "20260102T000000Z"


def test_load_latest_snapshot_prefers_sqlite_over_legacy_directory_state(tmp_path):
    model_state = _load_module("worker_model_state_test_sqlite_preferred", "services/freecad-worker/worker/model_state.py")

    legacy_dir = tmp_path / "20260101T000000Z"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "manifest.json").write_text('{"run_id": "20260101T000000Z", "model": {}}', encoding="utf-8")
    (legacy_dir / "inference_profile.json").write_text('{"system_message": "legacy"}', encoding="utf-8")

    model_state.persist_training_state(
        state_dir=tmp_path,
        run_id="run-sqlite",
        manifest={"model": {"model_id": "trained-freecad", "backend": "llama.cpp", "device": "cpu"}},
        inference_profile={"system_message": "sqlite", "examples": [], "retrieval_snippets": []},
        checkpoint_payload={"step": 2},
        optimizer_payload={"optimizer": {"name": "adamw"}},
        weights_payload={"parameter_strategy": "external-backend-managed"},
        lora_payload={"adapter_type": "metadata-profile"},
        embedding_index_payload={"documents": []},
    )

    snapshot = model_state.load_latest_snapshot(tmp_path)

    assert snapshot is not None
    assert snapshot.run_id == "run-sqlite"
    assert snapshot.path == tmp_path / model_state.SQLITE_DB_FILENAME
    assert snapshot.inference_profile["system_message"] == "sqlite"
