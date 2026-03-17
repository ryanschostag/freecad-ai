from pathlib import Path


def test_web_ui_uses_cpu_friendly_default_timeout_and_polling_tolerance():
    repo_root = Path(__file__).resolve().parents[2]
    app_js = (repo_root / "services" / "web-ui" / "static" / "app.js").read_text(encoding="utf-8")

    assert "setInterval(poll, 1500)" in app_js
    assert 'maxAttempts = 6' in app_js
    assert 'await sleep(2000);' in app_js


def test_web_ui_retries_transient_prompt_submission_failures_and_uses_longer_proxy_timeout():
    repo_root = Path(__file__).resolve().parents[2]
    app_js = (repo_root / "services" / "web-ui" / "static" / "app.js").read_text(encoding="utf-8")
    main_py = (repo_root / "services" / "web-ui" / "app" / "main.py").read_text(encoding="utf-8")
    compose = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")

    assert 'message.includes("HTTP 502")' in app_js
    assert 'message.includes("HTTP 503")' in app_js
    assert 'message.includes("HTTP 504")' in app_js
    assert 'message.includes("timed out")' in app_js
    assert 'timeout_s = float(os.getenv("WEBUI_API_TIMEOUT_S", "180"))' in main_py
    assert 'WEBUI_API_TIMEOUT_S=${WEBUI_API_TIMEOUT_S:-360}' in compose
