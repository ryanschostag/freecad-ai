from pathlib import Path


def test_web_ui_has_no_llm_max_tokens_controls():
    repo_root = Path(__file__).resolve().parents[2]
    app_js = (repo_root / "services" / "web-ui" / "static" / "app.js").read_text(encoding="utf-8")
    index_html = (repo_root / "services" / "web-ui" / "static" / "index.html").read_text(encoding="utf-8")

    assert 'llmMaxTokens' not in app_js
    assert 'maxTokens' not in app_js
    assert 'llmMaxTokens' not in index_html
    assert 'maxTokens' not in index_html


def test_api_accepts_messages_without_any_llm_max_tokens_fields():
    repo_root = Path(__file__).resolve().parents[2]
    sessions_py = (repo_root / "services" / "api" / "app" / "routes" / "sessions.py").read_text(encoding="utf-8")

    assert 'payload.get("llm_max_tokens")' not in sessions_py
    assert 'payload.get("max_tokens")' not in sessions_py
