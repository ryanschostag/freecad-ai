from pathlib import Path


def _block(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def test_llm_services_define_explicit_network_aliases():
    repo_root = Path(__file__).resolve().parents[2]
    compose = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")

    llm_block = _block(compose, "  llm:\n", "\n  llm-cuda:\n")
    assert "aliases:" in llm_block
    assert "          - llm\n" in llm_block
    assert "          - freecad-ai-llm\n" in llm_block

    cuda_block = _block(compose, "  llm-cuda:\n", "\n  llm-fake:\n")
    assert "aliases:" in cuda_block
    assert "          - llm-cuda\n" in cuda_block
    assert "          - llm-gpu\n" in cuda_block

    fake_block = _block(compose, "  llm-fake:\n", "\n  freecad-worker:\n")
    assert "aliases:" in fake_block
    assert "          - llm-fake\n" in fake_block
    assert "          - freecad-ai-llm-fake\n" in fake_block
