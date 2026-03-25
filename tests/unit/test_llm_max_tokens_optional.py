from pathlib import Path


def test_web_ui_sends_null_llm_max_tokens_when_blank():
    repo_root = Path(__file__).resolve().parents[2]
    app_js = (repo_root / "services" / "web-ui" / "static" / "app.js").read_text(encoding="utf-8")
    index_html = (repo_root / "services" / "web-ui" / "static" / "index.html").read_text(encoding="utf-8")

    assert "function optionalPositiveInt" in app_js
    assert 'llm_max_tokens: optionalPositiveInt($("llmMaxTokens").value)' in app_js
    assert 'placeholder="Automatic from context window"' in index_html


def test_api_accepts_nullable_llm_max_tokens():
    repo_root = Path(__file__).resolve().parents[2]
    sessions_py = (repo_root / "services" / "api" / "app" / "routes" / "sessions.py").read_text(encoding="utf-8")

    assert 'llm_max_tokens_raw = payload.get("llm_max_tokens")' in sessions_py
    assert 'llm_max_tokens = None' in sessions_py
    assert 'if llm_max_tokens <= 0:' in sessions_py
