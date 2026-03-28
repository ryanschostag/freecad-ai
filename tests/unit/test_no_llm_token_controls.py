from pathlib import Path


def test_repo_removes_all_llm_max_token_controls_from_public_entrypoints():
    repo_root = Path(__file__).resolve().parents[2]
    files = [
        repo_root / "services" / "web-ui" / "static" / "index.html",
        repo_root / "services" / "web-ui" / "static" / "app.js",
        repo_root / "services" / "api" / "app" / "routes" / "sessions.py",
        repo_root / "tools" / "cad_agent" / "cad_agent_cli.py",
    ]
    joined = "\n".join(path.read_text(encoding="utf-8") for path in files)
    assert "llmMaxTokens" not in joined
    assert "llm_max_tokens" not in joined
    assert 'id="maxTokens"' not in joined
    assert 'max_tokens: parseInt' not in joined
