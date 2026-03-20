from pathlib import Path


def test_test_runner_does_not_override_llm_base_url_for_unit_tests():
    repo_root = Path(__file__).resolve().parents[2]
    compose = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")

    test_runner_block = compose.split("  test-runner:")[1].split("  web-ui:")[0]
    assert "LLM_BASE_URL=http://llm-fake:8000" not in test_runner_block

    worker_test_block = compose.split("  freecad-worker-test:")[1].split("volumes:")[0]
    api_test_block = compose.split("  api-test:")[1].split("  test-runner:")[0]
    assert "LLM_BASE_URL=http://llm-fake:8000" in api_test_block
    assert "LLM_BASE_URL=http://llm-fake:8000" in worker_test_block
