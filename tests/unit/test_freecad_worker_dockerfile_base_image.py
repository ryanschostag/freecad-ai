from pathlib import Path


def test_freecad_worker_dockerfile_uses_python_slim_base_image() -> None:
    dockerfile = Path("services/freecad-worker/Dockerfile").read_text(encoding="utf-8")

    first_nonempty = next(line.strip() for line in dockerfile.splitlines() if line.strip())
    assert first_nonempty == "FROM python:3.11-slim"
    assert "FROM ubuntu:22.04" not in dockerfile
    assert "apt-get install -y --no-install-recommends" in dockerfile
    assert "freecad" in dockerfile
    assert 'CMD ["python","-m","worker.worker_main"]' in dockerfile
