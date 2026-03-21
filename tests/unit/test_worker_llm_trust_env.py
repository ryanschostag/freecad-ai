from pathlib import Path


def test_worker_llm_client_ignores_proxy_environment_for_internal_docker_calls():
    repo_root = Path(__file__).resolve().parents[2]
    llm_py = (repo_root / "services" / "freecad-worker" / "worker" / "llm.py").read_text(encoding="utf-8")

    assert 'httpx.Client(timeout=client_timeout, trust_env=False)' in llm_py
