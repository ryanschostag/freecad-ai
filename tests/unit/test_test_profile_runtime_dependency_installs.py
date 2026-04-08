from pathlib import Path

import yaml


def test_test_runner_does_not_install_pytest_at_container_startup():
    repo_root = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((repo_root / "docker-compose.yml").read_text(encoding="utf-8"))
    service = compose["services"]["test-runner"]

    build = service.get("build")
    assert isinstance(build, dict)
    assert build["context"] == "."
    assert build["dockerfile"] == "tests/Dockerfile.test-runner"
    assert "image" not in service
    assert service["command"] == ["pytest", "-vv", "--full-trace"]



def test_fake_llm_does_not_install_dependencies_at_container_startup():
    repo_root = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((repo_root / "docker-compose.yml").read_text(encoding="utf-8"))
    service = compose["services"]["llm-fake"]

    build = service.get("build")
    assert isinstance(build, dict)
    assert build["context"] == "."
    assert build["dockerfile"] == "tools/Dockerfile.fake-llm"
    assert "image" not in service
    assert service["command"] == [
        "uvicorn",
        "fake_llm_server:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
    ]



def test_test_runner_dockerfile_installs_test_requirements_during_build():
    repo_root = Path(__file__).resolve().parents[2]
    dockerfile = (repo_root / "tests" / "Dockerfile.test-runner").read_text(encoding="utf-8")

    assert "COPY tests/requirements.txt /tmp/tests-requirements.txt" in dockerfile
    assert "pip install --no-cache-dir -r /tmp/tests-requirements.txt" in dockerfile



def test_fake_llm_dockerfile_bakes_runtime_dependencies_during_build():
    repo_root = Path(__file__).resolve().parents[2]
    dockerfile = (repo_root / "tools" / "Dockerfile.fake-llm").read_text(encoding="utf-8")

    assert "pip install --no-cache-dir fastapi==0.115.0 uvicorn==0.30.6" in dockerfile
    assert "COPY tools/fake_llm_server.py /app/fake_llm_server.py" in dockerfile
