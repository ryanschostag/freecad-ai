from pathlib import Path


def _block(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def test_compose_pins_llama_cpp_images_and_healthchecks_cpu_service():
    repo_root = Path(__file__).resolve().parents[2]
    compose = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")

    llm_block = _block(compose, "  llm:\n", "\n  llm-cuda:\n")
    assert "image: ${LLAMA_CPP_SERVER_IMAGE:-ghcr.io/ggml-org/llama.cpp:server-b8475}" in llm_block
    assert "healthcheck:" in llm_block
    assert "test: [\"CMD\", \"/app/llama-server\", \"--version\"]" in llm_block


def test_compose_gates_worker_start_on_healthy_llm():
    repo_root = Path(__file__).resolve().parents[2]
    compose = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")

    worker_block = _block(compose, "  freecad-worker:\n", "\n  freecad-worker-test:\n")
    assert "llm:" in worker_block
    assert "condition: service_healthy" in worker_block
