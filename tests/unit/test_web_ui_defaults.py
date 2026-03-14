from pathlib import Path


def test_web_ui_uses_cpu_friendly_default_timeout_and_polling_tolerance():
    repo_root = Path(__file__).resolve().parents[2]
    html = (repo_root / "services" / "web-ui" / "static" / "index.html").read_text(encoding="utf-8")
    js = (repo_root / "services" / "web-ui" / "static" / "app.js").read_text(encoding="utf-8")

    assert 'id="timeoutSeconds"' in html
    assert 'value="900"' in html
    assert 'parseInt($("timeoutSeconds").value || "900", 10)' in js
    assert 'if (consecutiveFailures >= 5)' in js
    assert 'id="llmMaxTokens"' in html
    assert 'value="1200"' in html
    assert 'llm_max_tokens: parseInt($("llmMaxTokens").value || "1200", 10)' in js
