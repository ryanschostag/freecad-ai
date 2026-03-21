from pathlib import Path


def _block(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def test_runtime_services_define_host_gateway_mapping_for_internal_fallback():
    repo_root = Path(__file__).resolve().parents[2]
    compose = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")

    api_block = _block(compose, "  api:\n", "\n  api-test:\n")
    assert 'host.docker.internal:host-gateway' in api_block

    api_test_block = _block(compose, "  api-test:\n", "\n  # Run pytest inside Docker with all required services available.\n")
    assert 'host.docker.internal:host-gateway' in api_test_block

    worker_block = _block(compose, "  freecad-worker:\n", "\n  freecad-worker-test:\n")
    assert 'host.docker.internal:host-gateway' in worker_block

    worker_test_block = _block(compose, "  freecad-worker-test:\n", "\nvolumes:\n")
    assert 'host.docker.internal:host-gateway' in worker_test_block
