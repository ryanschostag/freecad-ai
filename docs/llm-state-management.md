# LLM state management

The CPU and GPU `llama.cpp` services now persist slot state files to a host-mounted directory that is derived from the selected model file.

## Directory layout

Given a model file path like:

```text
/models/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf
```

The container derives the state directory name from the model file name by replacing every period (`.`) with a hyphen (`-`):

```text
Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf
-> Qwen2-5-Coder-7B-Instruct-Q4_K_M-gguf
```

The resulting state path is:

```text
/models/Qwen2-5-Coder-7B-Instruct-Q4_K_M-gguf/state
```

Because the Docker Compose stack bind-mounts the host `./models` directory to `/models` inside the container, the corresponding host directory is:

```text
./models/Qwen2-5-Coder-7B-Instruct-Q4_K_M-gguf/state
```

## Why this exists

`llama.cpp` can persist slot state to disk via `--slot-save-path`. Persisting that directory on the host allows the local stack to keep model state across container restarts and rebuilds.

## Compose behavior

Both `llm` and `llm-cuda` now:

1. read the model path from `LLM_MODEL_PATH`
2. derive the state directory name from the selected model file
3. create `/models/<derived-name>/state` if needed
4. start `llama-server` with `--slot-save-path` pointing at that directory

## Related environment variables

These values are exposed in `.env.sample` and can be overridden in your shell or `.env` file:

- `LLM_MODEL_PATH`
- `LLM_THREADS`
- `LLM_CTX_SIZE`
- `LLM_CHAT_TEMPLATE`
- `LLM_N_GPU_LAYERS`

## CPU startup helper

`build-cpu.sh` now creates the host state directory before bringing the stack up. This guarantees the path exists on the host even before the first model request reaches `llama.cpp`.
