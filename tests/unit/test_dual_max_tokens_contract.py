from pathlib import Path


def test_web_and_api_support_legacy_and_optional_llm_max_tokens_contracts():
    repo_root = Path(__file__).resolve().parents[2]
    html = (repo_root / 'services' / 'web-ui' / 'static' / 'index.html').read_text(encoding='utf-8')
    js = (repo_root / 'services' / 'web-ui' / 'static' / 'app.js').read_text(encoding='utf-8')
    sessions_py = (repo_root / 'services' / 'api' / 'app' / 'routes' / 'sessions.py').read_text(encoding='utf-8')

    assert 'id="maxTokens"' in html
    assert 'value="2400"' in html
    assert 'id="llmMaxTokens"' in html
    assert 'placeholder="Automatic from context window"' in html
    assert 'max_tokens: parseInt($("maxTokens").value || "2400", 10)' in js
    assert 'llm_max_tokens: optionalPositiveInt($("llmMaxTokens").value)' in js
    assert 'requested_max_tokens_raw = payload.get("max_tokens")' in sessions_py
    assert 'llm_max_tokens_raw = payload.get("llm_max_tokens")' in sessions_py
