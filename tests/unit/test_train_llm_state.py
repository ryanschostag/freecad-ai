import importlib.util
import sqlite3
import sys
from pathlib import Path


def _load_train_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "tools" / "train_llm_state.py"
    spec = importlib.util.spec_from_file_location("train_llm_state_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[assignment]
    return module


def test_train_and_persist_creates_reusable_state_bundle_in_sqlite(tmp_path):
    train_mod = _load_train_module()
    doc_path = tmp_path / "guide.txt"
    doc_path.write_text("Use centered sketches and export STEP artifacts.", encoding="utf-8")
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(
        '{'
        '"model": {"model_id": "trained-freecad", "backend": "llama.cpp", "device": "cpu"},'
        '"examples": ['
        '{"prompt": "make a box", "response": "Create a new document and add Part::Box."},'
        '{"prompt": "export to step", "response": "Export with ImportGui.export."}'
        '],'
        f'"document_paths": ["{str(doc_path)}"],'
        '"optimizer": {"name": "adamw", "learning_rate": 0.0002}'
        '}',
        encoding="utf-8",
    )

    snapshot = train_mod.train_and_persist(str(dataset_path), state_dir=str(tmp_path / "state"), run_id="run-train")

    db_path = snapshot.path
    assert db_path.name == train_mod.model_state.SQLITE_DB_FILENAME
    assert db_path.exists()

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT manifest_json, inference_profile_json, embedding_index_json FROM state_runs WHERE run_id = ?",
            ("run-train",),
        ).fetchone()
        latest = conn.execute("SELECT run_id FROM state_latest WHERE singleton_id = 1").fetchone()

    assert row is not None
    assert latest is not None
    assert latest[0] == "run-train"
    assert '"examples": 2' in row[0]
    assert '"documents": 1' in row[0]
    assert '"prompt": "make a box"' in row[1]
    assert '"document_count": 1' in row[2]
