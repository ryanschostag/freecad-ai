#!/bin/bash
set -euo pipefail


down_file="down.log"
build_file="build.log"
up_file="up.log"
model_file="./models/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf"
model_filename="$(basename "$model_file")"
state_dir_name="${model_filename//./-}"
state_dir="./models/${state_dir_name}/state"

if [[ ! -f "$model_file" ]]; then
  echo "Missing model file: $model_file" >&2
  echo "Place the GGUF model at $model_file before starting the cpu profile." >&2
  exit 1
fi

mkdir -p "$state_dir"
echo "Using llama.cpp state directory: $state_dir"

time docker compose --profile cpu down 2>&1 | tee "$down_file"
sleep 1
time docker compose --profile cpu build --no-cache 2>&1 | tee "$build_file"
sleep 1
time docker compose --profile cpu up -d 2>&1 | tee "$up_file"

wait_for_url() {
  local url="$1"
  local name="$2"
  local timeout_s="${3:-120}"
  local start_ts
  start_ts="$(date +%s)"
  while true; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "$name is ready: $url"
      return 0
    fi
    if (( $(date +%s) - start_ts >= timeout_s )); then
      echo "Timed out waiting for $name at $url" >&2
      return 1
    fi
    sleep 2
  done
}

wait_for_url "http://localhost:8000/v1/models" "llm" 180
wait_for_url "http://localhost:8080/health" "api" 60

echo Complete!
