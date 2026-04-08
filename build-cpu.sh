#!/bin/bash
set -euo pipefail


down_file="down.log"
build_file="build.log"
up_file="up.log"
model_file="./models/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf"

if [[ ! -f "$model_file" ]]; then
  echo "Missing model file: $model_file" >&2
  echo "Place the GGUF model at $model_file before starting the cpu profile." >&2
  exit 1
fi

compose_down_best_effort() {
  local log_file="$1"
  set +e
  time docker compose --profile cpu down 2>&1 | tee "$log_file"
  local compose_status=${PIPESTATUS[0]}
  set -e
  if [[ $compose_status -ne 0 ]]; then
    echo "Warning: docker compose down failed and will be ignored because cleanup is best-effort." | tee -a "$log_file"
  fi
}

compose_down_best_effort "$down_file"
sleep 1
time docker compose --profile cpu build --no-cache 2>&1 | tee "$build_file"
sleep 1
time docker compose --profile cpu up -d 2>&1 | tee "$up_file"

echo Complete!
