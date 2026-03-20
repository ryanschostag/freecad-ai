from pathlib import Path


def test_worker_llm_module_is_real_code_not_placeholder_text():
    repo_root = Path(__file__).resolve().parents[2]
    llm_py = (repo_root / "services" / "freecad-worker" / "worker" / "llm.py").read_text(encoding="utf-8")

    assert "full llm.py content omitted" not in llm_py
    assert "def chat(" in llm_py
    assert "def _candidate_base_urls(" in llm_py
    assert "import httpx" in llm_py
