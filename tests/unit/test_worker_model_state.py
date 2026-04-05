import importlib.util
import json
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


def test_persist_training_state_writes_expected_files_and_latest_pointer(tmp_path):
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

    assert snapshot.path == tmp_path / "run-001"
    for name in (
        "manifest.json",
        "checkpoint.json",
        "weights.json",
        "lora_adapter.json",
        "optimizer_state.json",
        "embedding_index.json",
        "inference_profile.json",
    ):
        assert (snapshot.path / name).exists(), name

    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest["run_id"] == "run-001"
    assert latest["manifest_path"] == "run-001/manifest.json"


def test_load_latest_snapshot_falls_back_to_latest_run_directory(tmp_path):
    model_state = _load_module("worker_model_state_test_dirs", "services/freecad-worker/worker/model_state.py")

    for run_id in ("20260101T000000Z", "20260102T000000Z"):
        run_dir = tmp_path / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "manifest.json").write_text(json.dumps({"run_id": run_id, "model": {}}), encoding="utf-8")
        (run_dir / "inference_profile.json").write_text(json.dumps({"system_message": run_id}), encoding="utf-8")

    snapshot = model_state.load_latest_snapshot(tmp_path)

    assert snapshot is not None
    assert snapshot.run_id == "20260102T000000Z"
    assert snapshot.inference_profile["system_message"] == "20260102T000000Z"
