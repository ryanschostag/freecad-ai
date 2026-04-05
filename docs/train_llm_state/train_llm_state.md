# `tools/train_llm_state.py` Guide

This document explains how to use `tools/train_llm_state.py` to generate and persist reusable LLM training state for the FreeCAD-AI stack.

The script does **not** train a binary model in the framework-specific sense. Instead, it creates a durable, structured state bundle that the repository can reuse across container rebuilds and future runs. That bundle can include:

- a generated `manifest.json`
- a generated `checkpoint.json`
- a generated `weights.json`
- a generated `lora_adapter.json`
- a generated `optimizer_state.json`
- a generated `embedding_index.json`
- a generated `inference_profile.json`
- optional copies of externally produced artifacts imported from paths you provide
- a root-level `latest.json` pointer so the worker can find the most recent run

## What the script is for

Use this script when you want to:

- persist reusable model state under `data/llm/state/`
- seed the worker with repository-specific examples and documents
- preserve model-related metadata across container rebuilds
- import external training artifacts into a mounted state directory
- create repeatable state bundles during local development, CI, or containerized workflows

## Where the output goes

By default, the script writes to the resolved LLM state directory:

- CLI override: `--state-dir`
- otherwise environment variable: `LLM_STATE_DIR`
- otherwise default: `/data/llm/state`

In local Docker Compose usage, that directory is expected to be backed by a mounted host path such as:

- host: `./data/llm/state`
- container: `/data/llm/state`

## Generated output layout

A successful run creates a new subdirectory named after the run id.

Example:

```text
/data/llm/state/
  latest.json
  20260404T231500Z/
    manifest.json
    checkpoint.json
    weights.json
    lora_adapter.json
    optimizer_state.json
    embedding_index.json
    inference_profile.json
```

If the dataset imports existing external artifacts, the run directory can also contain files or folders such as:

```text
    imported_checkpoint.bin
    imported_weights.safetensors
    imported_lora_adapter/
    imported_optimizer_state.pt
    imported_embedding_index.faiss
```

## Command-line usage

### Basic usage

```bash
python tools/train_llm_state.py --dataset docs/train_llm_state/minimal_dataset.json
```

### Explicit state directory

```bash
python tools/train_llm_state.py \
  --dataset docs/train_llm_state/minimal_dataset.json \
  --state-dir ./data/llm/state
```

### Explicit run id

```bash
python tools/train_llm_state.py \
  --dataset docs/train_llm_state/minimal_dataset.json \
  --state-dir ./data/llm/state \
  --run-id freecad-profile-v1
```

## CLI arguments

### `--dataset`
Required. Path to a JSON dataset/config file.

### `--state-dir`
Optional. Overrides the effective LLM state directory for this run.

### `--run-id`
Optional. Lets you choose a stable identifier instead of the default UTC timestamp.

## Dataset/config schema

The script reads one JSON file and supports four main kinds of input:

### 1. Model metadata

```json
{
  "model": {
    "model_id": "trained-freecad-profile",
    "backend": "llama.cpp",
    "device": "cpu"
  }
}
```

If `model` is omitted, fallback values are built from top-level `model_id`, `backend`, and `device`, then finally defaulted.

### 2. Fine-tuning style examples

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

These examples are used to build:

- `checkpoint.json` summary metadata
- `weights.json` metadata summary
- `lora_adapter.json` style-token metadata
- `optimizer_state.json` completed-step metadata
- `inference_profile.json` reusable examples injected into later worker prompts

### 3. Embedded documents

You can include documents inline:

```json
{
  "documents": [
    "Prefer stable object names and explicit document recompute calls.",
    "Use STEP for interchange and STL for meshes when requested."
  ]
}
```

These documents help create:

- `embedding_index.json`
- `inference_profile.json` retrieval snippets

### 4. External document paths

You can reference text files on disk:

```json
{
  "document_paths": [
    "./docs/models-sources.md",
    "./docs/operational_runbook.md"
  ]
}
```

Each referenced file is read as UTF-8 text and folded into the generated embedding snapshot.

## Optional import paths for externally produced artifacts

If you already have artifacts from another training system, add any of the following keys:

- `checkpoint_path`
- `weights_path`
- `lora_adapter_path`
- `optimizer_state_path`
- `embedding_index_path`

Example:

```json
{
  "weights_path": "./artifacts/model.safetensors",
  "lora_adapter_path": "./artifacts/lora_adapter",
  "embedding_index_path": "./artifacts/embedding_index.faiss"
}
```

When present, the script copies those artifacts into the new run directory and records them in `manifest.json` under `imported_artifacts`.

## What gets generated from the dataset

### `manifest.json`
Top-level description of the run, including:

- `run_id`
- source dataset path
- dataset hash
- model metadata
- training summary counts
- generated file paths
- imported artifact paths when provided

### `checkpoint.json`
A checkpoint summary with fields such as:

- `epoch`
- `step`
- `status`
- dataset hash

### `weights.json`
A structured metadata placeholder describing the base model and the dataset. This repository intentionally records reusable state even when framework-native weight generation is external.

### `lora_adapter.json`
A lightweight adapter-style metadata profile generated from example responses. It derives style tokens from response text and stores a bounded `rank`.

### `optimizer_state.json`
Optimizer metadata, either from your dataset or a default fallback:

```json
{
  "name": "adamw",
  "learning_rate": 0.0001
}
```

### `embedding_index.json`
A document snapshot derived from inline documents and/or referenced text files. Each document entry stores:

- synthetic id
- SHA-256 hash
- text snippet

### `inference_profile.json`
The worker-facing reusable profile containing:

- model metadata
- system instruction text
- concise prompt/response examples
- retrieval snippets

This is the main runtime artifact the worker reuses during future LLM requests.

### `latest.json`
A root-level pointer that tells the worker which run is current.

## Example 1: minimal dataset

File: `docs/train_llm_state/minimal_dataset.json`

```bash
python tools/train_llm_state.py \
  --dataset docs/train_llm_state/minimal_dataset.json \
  --state-dir ./data/llm/state
```

Use this when you want the smallest valid reusable state bundle with:

- model metadata
- a few examples
- a few inline documents

## Example 2: dataset with external documents

File: `docs/train_llm_state/dataset_with_document_paths.json`

```bash
python tools/train_llm_state.py \
  --dataset docs/train_llm_state/dataset_with_document_paths.json \
  --state-dir ./data/llm/state
```

Use this when you want to build the embedding snapshot from repository docs or other local text files.

## Example 3: dataset that imports existing artifacts

File: `docs/train_llm_state/dataset_with_imported_artifacts.json`

Before running it, update the placeholder paths so they point to real files or directories on your machine.

```bash
python tools/train_llm_state.py \
  --dataset docs/train_llm_state/dataset_with_imported_artifacts.json \
  --state-dir ./data/llm/state \
  --run-id imported-freecad-profile
```

Use this when external training infrastructure already produced artifacts you want this stack to preserve and reference.

## Example workflow with Docker Compose

### 1. Configure the mount

In `.env` or your shell:

```env
LLM_STATE_HOST_DIR=./data/llm/state
LLM_STATE_DIR=/data/llm/state
```

### 2. Generate the state bundle

```bash
python tools/train_llm_state.py \
  --dataset docs/train_llm_state/minimal_dataset.json \
  --state-dir ./data/llm/state
```

### 3. Start the stack

```bash
docker compose --profile cpu up -d --build
```

### 4. Runtime effect

At runtime, the worker loads the latest snapshot and uses `inference_profile.json` to enrich later model requests with persisted FreeCAD-oriented guidance.

## Expected JSON output from the script

The script prints a JSON summary to stdout.

Example:

```json
{
  "run_id": "20260404T231500Z",
  "state_path": "/absolute/path/to/data/llm/state/20260404T231500Z",
  "latest_pointer": "/absolute/path/to/data/llm/state/latest.json"
}
```

## Failure cases and troubleshooting

### Run id already exists
If `--run-id` points at an existing folder, the script raises an error instead of overwriting the run.

Fix:

- choose a different `--run-id`, or
- remove the old run if it is no longer needed

### Imported artifact path does not exist
If any import path is invalid, the script raises a model-state error.

Fix:

- verify the file or directory exists
- verify the path is spelled correctly
- verify you are running the command from the expected working directory, or use absolute paths

### Referenced documents fail to load
`document_paths` are read as UTF-8 text.

Fix:

- use UTF-8 text files
- confirm the files exist and are readable
- avoid pointing `document_paths` at binary files

### The stack does not seem to reuse the generated state
Check:

- `latest.json` exists in the state root
- the worker can read `LLM_STATE_DIR`
- Docker Compose is mounting the same host directory you trained into
- the desired run contains `inference_profile.json`

## Recommendations

- keep example responses concise and repository-specific
- prefer high-signal documents instead of dumping large unrelated files
- use explicit `--run-id` values for named releases or milestone states
- keep imported artifact paths stable when using CI or shared environments
- treat `data/llm/state/` as durable state and back it up if it matters

## Related files

- `tools/train_llm_state.py`
- `services/freecad-worker/worker/model_state.py`
- `services/freecad-worker/worker/llm.py`
- `services/freecad-worker/worker/settings.py`
- `docker-compose.yml`
- `docs/testing.md`
