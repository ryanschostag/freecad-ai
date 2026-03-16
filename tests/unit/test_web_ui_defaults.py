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


def test_web_ui_retries_transient_prompt_submission_failures_and_uses_longer_proxy_timeout():
    repo_root = Path(__file__).resolve().parents[2]
    js = (repo_root / "services" / "web-ui" / "static" / "app.js").read_text(encoding="utf-8")
    main_py = (repo_root / "services" / "web-ui" / "app" / "main.py").read_text(encoding="utf-8")
    compose = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")

    assert 'async function sendPromptRequestWithRetry(sessionId, payload, maxAttempts = 6)' in js
    assert 'message.includes("HTTP 503")' in js
    assert 'await sleep(2000);' in js
    assert 'timeout_s = float(os.getenv("WEBUI_API_TIMEOUT_S", "180"))' in main_py
    assert 'WEBUI_API_TIMEOUT_S=180' in compose
