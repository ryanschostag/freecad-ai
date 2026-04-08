from pathlib import Path


def _read(path: str) -> str:
    repo_root = Path(__file__).resolve().parents[2]
    return (repo_root / path).read_text(encoding="utf-8")


def test_web_ui_dockerfile_uses_pip_timeout_and_retries():
    dockerfile = _read("services/web-ui/Dockerfile")
    assert "PIP_DEFAULT_TIMEOUT=180" in dockerfile
    assert "PIP_RETRIES=10" in dockerfile
    assert "pip install --no-cache-dir -r /app/requirements.txt" in dockerfile


def test_fake_llm_dockerfile_uses_pip_timeout_and_retries():
    dockerfile = _read("tools/Dockerfile.fake-llm")
    assert "PIP_DEFAULT_TIMEOUT=180" in dockerfile
    assert "PIP_RETRIES=10" in dockerfile
    assert "pip install --no-cache-dir fastapi==0.115.0 uvicorn==0.30.6" in dockerfile


def test_test_runner_dockerfile_uses_pip_timeout_and_retries():
    dockerfile = _read("tests/Dockerfile.test-runner")
    assert "PIP_DEFAULT_TIMEOUT=180" in dockerfile
    assert "PIP_RETRIES=10" in dockerfile
    assert "pip install --no-cache-dir -r /tmp/tests-requirements.txt" in dockerfile


def test_api_and_worker_dockerfiles_use_pip_timeout_and_retries():
    api_dockerfile = _read("services/api/Dockerfile")
    worker_dockerfile = _read("services/freecad-worker/Dockerfile")

    assert "PIP_DEFAULT_TIMEOUT=180" in api_dockerfile
    assert "PIP_RETRIES=10" in api_dockerfile
    assert "pip install --no-cache-dir -e ." in api_dockerfile
    assert "pip install --no-cache-dir -r /app/tests/requirements.txt" in api_dockerfile

    assert "PIP_DEFAULT_TIMEOUT=180" in worker_dockerfile
    assert "PIP_RETRIES=10" in worker_dockerfile
    assert "python -m pip install --no-cache-dir -e ." in worker_dockerfile
