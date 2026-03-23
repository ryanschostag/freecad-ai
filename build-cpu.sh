#!/bin/bash
set -euo pipefail


down_file="down.log"
build_file="build.log"
up_file="up.log"
model_file="./models/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf"
model_filename="$(basename "$model_file")"
state_dir_name="${model_filename//./-}"
state_dir="./models/${state_dir_name}/state"
llm_ready_timeout_s="${LLM_READY_TIMEOUT_S:-1200}"
llm_request_timeout_s="${LLM_REQUEST_TIMEOUT_S:-120}"
api_ready_timeout_s="${API_READY_TIMEOUT_S:-90}"

if [[ ! -f "$model_file" ]]; then
  echo "Missing model file: $model_file" >&2
  echo "Place the GGUF model at $model_file before starting the cpu profile." >&2
  exit 1
fi

mkdir -p "$state_dir"
echo "Using llama.cpp state directory: $state_dir"
echo "LLM readiness timeout: ${llm_ready_timeout_s}s"
echo "LLM probe request timeout: ${llm_request_timeout_s}s"

time docker compose --profile cpu down 2>&1 | tee "$down_file"
sleep 1
time docker compose --profile cpu build --no-cache 2>&1 | tee "$build_file"
sleep 1
time docker compose --profile cpu up -d 2>&1 | tee "$up_file"

check_service_running() {
  local service="$1"
  local container_id
  local state
  container_id="$(docker compose --profile cpu ps -q "$service" 2>/dev/null || true)"
  if [[ -z "$container_id" ]]; then
    return 0
  fi
  state="$(docker inspect -f {{.State.Status}} "$container_id" 2>/dev/null || true)"
  case "$state" in
    running|restarting|created|starting|healthy)
      return 0
      ;;
    exited|dead)
      echo "Service $service is $state; aborting readiness wait early." >&2
      docker compose --profile cpu ps "$service" >&2 || true
      print_service_logs "$service"
      return 1
      ;;
    *)
      return 0
      ;;
  esac
}

print_service_logs() {
  local service="$1"
  echo
  echo "===== docker compose logs: ${service} =====" >&2
  docker compose --profile cpu logs --tail=200 "$service" >&2 || true
}

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
      echo "Timed out waiting for $name at $url after ${timeout_s}s" >&2
      return 1
    fi
    sleep 2
  done
}

wait_for_llm_http() {
  local timeout_s="$1"
  local start_ts
  start_ts="$(date +%s)"
  while true; do
    check_service_running llm || return 1
    if curl -fsS "http://localhost:8000/health" >/dev/null 2>&1 || curl -fsS "http://localhost:8000/v1/models" >/dev/null 2>&1; then
      echo "llm HTTP endpoint is reachable: http://localhost:8000"
      return 0
    fi
    if (( $(date +%s) - start_ts >= timeout_s )); then
      echo "Timed out waiting for llm HTTP endpoint at http://localhost:8000 after ${timeout_s}s" >&2
      print_service_logs llm
      return 1
    fi
    sleep 2
  done
}

wait_for_llm_inference() {
  local timeout_s="$1"
  local request_timeout_s="$2"
  local start_ts
  local payload
  start_ts="$(date +%s)"
  payload='{"prompt":"<|im_start|>user\nRespond with READY only.\n<|im_end|>\n<|im_start|>assistant\n","n_predict":1,"temperature":0,"stop":["<|im_end|>","</s>","<|endoftext|>"]}'
  while true; do
    check_service_running llm || return 1
    if curl -fsS --max-time "$request_timeout_s" -H 'Content-Type: application/json' -d "$payload" http://localhost:8000/completion >/dev/null 2>&1; then
      echo "llm inference is ready: http://localhost:8000/completion"
      return 0
    fi
    if (( $(date +%s) - start_ts >= timeout_s )); then
      echo "Timed out waiting for llm inference readiness at http://localhost:8000/completion after ${timeout_s}s" >&2
      print_service_logs llm
      return 1
    fi
    sleep 3
  done
}

wait_for_worker_llm_route() {
  local timeout_s="$1"
  local start_ts
  start_ts="$(date +%s)"
  while true; do
    if docker compose --profile cpu exec -T freecad-worker python - <<'PY' >/dev/null 2>&1
import os
import socket
from urllib.parse import urlsplit
from urllib.request import urlopen

base_url = os.environ.get("LLM_BASE_URL", "http://freecad-ai-llm:8000").rstrip("/")
parsed = urlsplit(base_url)
host = parsed.hostname
port = parsed.port or (443 if parsed.scheme == "https" else 80)
if not host:
    raise SystemExit(1)
socket.getaddrinfo(host, port)
for path in ("/health", "/v1/models", "/"):
    try:
        with urlopen(base_url + path, timeout=5) as response:
            if 200 <= getattr(response, "status", 0) < 300:
                raise SystemExit(0)
    except Exception:
        continue
raise SystemExit(1)
PY
    then
      echo "worker can resolve and reach configured LLM endpoint from inside Docker network"
      return 0
    fi
    if (( $(date +%s) - start_ts >= timeout_s )); then
      echo "Timed out waiting for freecad-worker to resolve and reach its configured LLM endpoint after ${timeout_s}s" >&2
      print_service_logs freecad-worker
      print_service_logs llm
      return 1
    fi
    sleep 2
  done
}

wait_for_llm_http "$llm_ready_timeout_s"
wait_for_llm_inference "$llm_ready_timeout_s" "$llm_request_timeout_s"
wait_for_worker_llm_route "$llm_ready_timeout_s"
wait_for_url "http://localhost:8080/health" "api" "$api_ready_timeout_s" || {
  print_service_logs api
  exit 1
}

echo Complete!
