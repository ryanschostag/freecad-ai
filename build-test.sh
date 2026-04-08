#!/bin/bash
set -euo pipefail

COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.test-override.yml)
PROFILE=(--profile test)

down_file="down.log"
build_file="build.log"
up_file="up.log"
run_file="run.log"

rm -f *.log

compose_down_best_effort() {
  local log_file="$1"
  set +e
  time docker compose "${COMPOSE_FILES[@]}" "${PROFILE[@]}" down 2>&1 | tee "$log_file"
  local compose_status=${PIPESTATUS[0]}
  set -e
  if [[ $compose_status -ne 0 ]]; then
    echo "Warning: docker compose down failed and will be ignored because cleanup is best-effort." | tee -a "$log_file"
  fi
}

compose_down_best_effort "$down_file"
sleep 1
time docker compose "${COMPOSE_FILES[@]}" "${PROFILE[@]}" build --no-cache 2>&1 | tee "$build_file"
sleep 1
time docker compose "${COMPOSE_FILES[@]}" "${PROFILE[@]}" up -d 2>&1 | tee "$up_file"
sleep 1
time docker compose "${COMPOSE_FILES[@]}" "${PROFILE[@]}" run --rm test-runner 2>&1 | tee "$run_file"
sleep 1
compose_down_best_effort "$down_file"

echo Complete!
