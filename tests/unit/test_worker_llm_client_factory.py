from pathlib import Path


def test_worker_llm_uses_client_factory_with_trust_env_fallback():
    repo_root = Path(__file__).resolve().parents[2]
    llm_py = (repo_root / "services" / "freecad-worker" / "worker" / "llm.py").read_text(encoding="utf-8")

    assert "def _build_http_client(" in llm_py
    assert "httpx.Client(timeout=client_timeout, trust_env=False)" in llm_py
    assert "except TypeError:" in llm_py
    assert "return httpx.Client(timeout=client_timeout)" in llm_py
    assert "with _build_http_client(client_timeout) as client:" in llm_py
