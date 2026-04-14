# `tools/train_llm_state.py`

`tools/train_llm_state.py` builds and persists reusable LLM training state for the FreeCAD AI stack.

It is intended for lightweight repository-specific adaptation rather than heavyweight framework-native training. The script packages examples, documents, optional imported artifacts, and model metadata into the persistent state store used by the worker.

## What the script writes

The current implementation writes to the configured LLM state directory and stores run data in a SQLite database named `llm-state.sqlite3`.

By default:
- host path: `./data/llm/state`
- container path: `/data/llm/state`
- SQLite file: `llm-state.sqlite3`

Each run creates a row in `state_runs` and updates the singleton `state_latest` pointer.

## Why this matters

The worker can load the latest `inference_profile_json` and reuse it during later CAD-generation requests. That lets you preserve:
- prompt/response examples
- repository-specific instructions
- retrieval snippets built from inline documents or referenced files
- metadata about imported artifacts from external training workflows

## CLI usage

### Minimal example

```bash
python tools/train_llm_state.py --dataset docs/train_llm_state/minimal_dataset.json
```

### Explicit state directory

```bash
python tools/train_llm_state.py   --dataset docs/train_llm_state/minimal_dataset.json   --state-dir ./data/llm/state
```

### Explicit run id

```bash
python tools/train_llm_state.py   --dataset docs/train_llm_state/minimal_dataset.json   --state-dir ./data/llm/state   --run-id freecad-profile-v1
```

## Arguments

### `--dataset`
Required. Path to a JSON file describing model metadata, examples, documents, and optional imported artifacts.

### `--state-dir`
Optional. Overrides the effective LLM state directory.

### `--run-id`
Optional. Uses a stable identifier instead of the default UTC timestamp.

## Dataset schema

The dataset file is JSON and can include these keys.

### `model`

```json
{
  "model": {
    "model_id": "trained-freecad-profile",
    "backend": "llama.cpp",
    "device": "cpu"
  }
}
```

If omitted, fallback values are derived from top-level fields and then defaulted.

### `examples`

```json
{
  "examples": [
    {
      "prompt": "Create a 10x20x30 mm box and export it as STEP.",
      "response": "Create a new FreeCAD document, add Part::Box, set Length/Width/Height, recompute, then export as STEP."
    }
  ]
}
```

These examples are folded into the generated inference profile and metadata payloads.

### `documents`

Inline document snippets can be embedded directly:

```json
{
  "documents": [
    "Prefer stable object names and explicit recompute calls.",
    "Use STEP for interchange and STL for mesh output when requested."
  ]
}
```

### `document_paths`

Referenced files are read as UTF-8 text and included in the retrieval snapshot:

```json
{
  "document_paths": [
    "./docs/models-sources.md",
    "./docs/operational-runbook.md"
  ]
}
```

### Optional imported artifact paths

The script also accepts:
- `checkpoint_path`
- `weights_path`
- `lora_adapter_path`
- `optimizer_state_path`
- `embedding_index_path`

These paths are validated and imported into SQLite-backed state storage as binary payloads.

## What gets generated logically

For each run, the script builds the following payloads:
- `manifest_json`
- `inference_profile_json`
- `checkpoint_json`
- `optimizer_state_json`
- `weights_json`
- `lora_adapter_json`
- `embedding_index_json`

The manifest stores SQLite-style logical paths such as:
- `sqlite:///.../llm-state.sqlite3#run_id=<RUN_ID>&field=inference_profile_json`

## Output example

The script prints JSON similar to:

```json
{
  "run_id": "20260413T230000Z",
  "state_path": "/absolute/path/to/data/llm/state/llm-state.sqlite3",
  "latest_pointer": "/absolute/path/to/data/llm/state/llm-state.sqlite3"
}
```

## Example datasets in this repository

- `docs/train_llm_state/minimal_dataset.json`
- `docs/train_llm_state/dataset_with_imported_artifacts.json`
- `docs/train_llm_state/dataset_with_document_paths.json`

## Recommended workflow

1. Prepare a dataset JSON file.
2. Run `tools/train_llm_state.py`.
3. Confirm that `llm-state.sqlite3` exists under the configured state directory.
4. Restart or reuse the worker with the same mounted state directory.
5. Submit a new job and verify the worker loaded the latest inference profile.

## Troubleshooting

### `State run already exists`
Use a different `--run-id` or remove the conflicting run from the SQLite database if appropriate.

### `Imported artifact does not exist`
Check the path in the dataset file. Imported artifact paths are resolved before insertion.

### Expected JSON files are not present on disk
That is normal for the current implementation. The persistent state store is SQLite-backed, and payloads are stored in database fields rather than individual JSON files.
