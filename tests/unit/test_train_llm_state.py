import importlib.util
import json
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


def test_train_and_persist_creates_reusable_state_bundle(tmp_path):
    train_mod = _load_train_module()
    doc_path = tmp_path / "guide.txt"
    doc_path.write_text("Use centered sketches and export STEP artifacts.", encoding="utf-8")
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(
        json.dumps(
            {
                "model": {"model_id": "trained-freecad", "backend": "llama.cpp", "device": "cpu"},
                "examples": [
                    {"prompt": "make a box", "response": "Create a new document and add Part::Box."},
                    {"prompt": "export to step", "response": "Export with ImportGui.export."},
                ],
                "document_paths": [str(doc_path)],
                "optimizer": {"name": "adamw", "learning_rate": 0.0002},
            }
        ),
        encoding="utf-8",
    )

    snapshot = train_mod.train_and_persist(str(dataset_path), state_dir=str(tmp_path / "state"), run_id="run-train")

    manifest = json.loads((snapshot.path / "manifest.json").read_text(encoding="utf-8"))
    profile = json.loads((snapshot.path / "inference_profile.json").read_text(encoding="utf-8"))
    embedding_index = json.loads((snapshot.path / "embedding_index.json").read_text(encoding="utf-8"))

    assert manifest["training_summary"] == {"examples": 2, "documents": 1}
    assert profile["examples"][0]["prompt"] == "make a box"
    assert embedding_index["document_count"] == 1
    assert (snapshot.path.parent / "latest.json").exists()
