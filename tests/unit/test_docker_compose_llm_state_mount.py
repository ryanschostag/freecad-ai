from pathlib import Path

import yaml


def test_docker_compose_mounts_persisted_llm_state_for_runtime_services():
    repo_root = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((repo_root / "docker-compose.yml").read_text(encoding="utf-8"))
    expected_mount = "${LLM_STATE_HOST_DIR:-./data/llm/state}:${LLM_STATE_DIR:-/data/llm/state}"
    expected_env = "LLM_STATE_DIR=${LLM_STATE_DIR:-/data/llm/state}"

    for service_name in ("api", "api-test", "test-runner", "freecad-worker", "freecad-worker-test"):
        service = compose["services"][service_name]
        assert expected_mount in service.get("volumes", [])
        assert expected_env in service.get("environment", [])
