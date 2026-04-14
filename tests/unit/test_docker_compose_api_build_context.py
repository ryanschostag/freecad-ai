from pathlib import Path

import yaml


def test_api_services_use_repo_root_build_context_for_api_dockerfile():
    repo_root = Path(__file__).resolve().parents[2]
    compose_path = repo_root / "docker-compose.yml"

    data = yaml.safe_load(compose_path.read_text())
    services = data["services"]

    for service_name in ("api", "api-test"):
        build = services[service_name]["build"]
        assert isinstance(build, dict), f"{service_name} build config must be a mapping"
        assert build["context"] == ".", (
            f"{service_name} must build from the repo root so Docker can COPY repo-level tests/ and tools/"
        )
        assert build["dockerfile"] == "services/api/Dockerfile"


def test_api_dockerfile_copies_repo_level_tests_and_tools():
    repo_root = Path(__file__).resolve().parents[2]
    dockerfile_path = repo_root / "services" / "api" / "Dockerfile"
    dockerfile = dockerfile_path.read_text()

    assert "COPY tests /app/tests" in dockerfile
    assert "COPY tools /app/tools" in dockerfile
