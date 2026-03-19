from pathlib import Path


def test_cpu_worker_and_api_use_resolvable_llm_alias_and_worker_depends_on_llm():
    repo_root = Path(__file__).resolve().parents[2]
    compose = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")

    assert '- LLM_BASE_URL=http://freecad-ai-llm:8000' in compose
    worker_block = compose.split('  freecad-worker:')[1].split('  freecad-worker-test:')[0]
    assert '      - llm' in worker_block


def test_gpu_override_points_to_existing_llm_cuda_service():
    repo_root = Path(__file__).resolve().parents[2]
    override = (repo_root / "docker-compose.gpu.override.yml").read_text(encoding="utf-8")

    assert 'http://llm-cuda:8000' in override
    assert 'http://llm-gpu:8000' not in override
