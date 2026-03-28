from pathlib import Path


def test_api_and_web_ui_do_not_expose_llm_max_tokens():
    repo_root = Path(__file__).resolve().parents[2]
    sessions_py = (repo_root / "services" / "api" / "app" / "routes" / "sessions.py").read_text(encoding="utf-8")
    html = (repo_root / "services" / "web-ui" / "static" / "index.html").read_text(encoding="utf-8")
    js = (repo_root / "services" / "web-ui" / "static" / "app.js").read_text(encoding="utf-8")

    assert 'id="maxTokens"' not in html
    assert 'id="llmMaxTokens"' not in html
    assert 'max_tokens' not in js
    assert 'llm_max_tokens' not in js
    assert 'payload.get("max_tokens")' not in sessions_py
    assert 'payload.get("llm_max_tokens")' not in sessions_py
