from pathlib import Path


def test_api_dockerfile_installs_runtime_requirements_before_editable_package() -> None:
    text = Path("services/api/Dockerfile").read_text()

    assert "COPY services/api/requirements.docker.txt /tmp/requirements.docker.txt" in text
    assert "pip install --no-cache-dir --progress-bar off -v -r /tmp/requirements.docker.txt" in text
    assert "pip install --no-cache-dir -e . --no-deps --progress-bar off -v" in text


def test_api_pyproject_does_not_duplicate_pgvector_dependency() -> None:
    text = Path("services/api/pyproject.toml").read_text()

    assert text.count('"pgvector==0.3.2"') == 1
    assert '"pgvector>=0.2.5"' not in text
