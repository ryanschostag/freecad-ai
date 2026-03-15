#!/bin/bash
set -euo pipefail

COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.test-override.yml)
PROFILE=(--profile test)

down_file="down.log"
build_file="build.log"
up_file="up.log"
run_file="run.log"
model_file="./models/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf"
model_filename="$(basename "$model_file")"
state_dir_name="${model_filename//./-}"
state_dir="./models/${state_dir_name}/state"

rm -f *.log

if [[ ! -f "$model_file" ]]; then
  echo "Missing model file: $model_file" >&2
  echo "Place the GGUF model at $model_file before starting the cpu profile." >&2
  exit 1
fi

mkdir -p "$state_dir"
echo "Using llama.cpp state directory: $state_dir"

time docker compose "${COMPOSE_FILES[@]}" "${PROFILE[@]}" down 2>&1 | tee $down_file
sleep 1
time docker compose "${COMPOSE_FILES[@]}" "${PROFILE[@]}" build --no-cache 2>&1 | tee $build_file
sleep 1
time docker compose "${COMPOSE_FILES[@]}" "${PROFILE[@]}" up -d 2>&1 | tee $up_file
sleep 1
time docker compose "${COMPOSE_FILES[@]}" "${PROFILE[@]}" run --rm test-runner 2>&1 | tee $run_file
sleep 1
time docker compose "${COMPOSE_FILES[@]}" "${PROFILE[@]}" down

echo Complete!
