from pathlib import Path


def test_api_and_web_ui_wire_max_tokens_to_worker_job():
    repo_root = Path(__file__).resolve().parents[2]
    sessions_py = (repo_root / "services" / "api" / "app" / "routes" / "sessions.py").read_text(encoding="utf-8")
    html = (repo_root / "services" / "web-ui" / "static" / "index.html").read_text(encoding="utf-8")
    js = (repo_root / "services" / "web-ui" / "static" / "app.js").read_text(encoding="utf-8")

    assert 'id="maxTokens"' in html
    assert 'value="2400"' in html
    assert 'max_tokens: parseInt($("maxTokens").value || "2400", 10)' in js
    assert 'requested_max_tokens_raw = payload.get("max_tokens")' in sessions_py
    assert '"max_tokens": requested_max_tokens' in sessions_py
