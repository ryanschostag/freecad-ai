from pathlib import Path


def test_web_and_api_remove_dual_llm_max_tokens_contracts():
    repo_root = Path(__file__).resolve().parents[2]
    html = (repo_root / 'services' / 'web-ui' / 'static' / 'index.html').read_text(encoding='utf-8')
    js = (repo_root / 'services' / 'web-ui' / 'static' / 'app.js').read_text(encoding='utf-8')
    sessions_py = (repo_root / 'services' / 'api' / 'app' / 'routes' / 'sessions.py').read_text(encoding='utf-8')

    for token in ['maxTokens', 'llmMaxTokens', 'max_tokens', 'llm_max_tokens']:
        assert token not in html
        assert token not in js
    assert 'max_tokens' not in sessions_py
    assert 'llm_max_tokens' not in sessions_py
