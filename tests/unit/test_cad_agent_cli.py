import json
from types import SimpleNamespace

import pytest


@pytest.fixture()
def cli(tmp_path):
    """Load the CLI module by file path so tests don't depend on PYTHONPATH."""
    import importlib.util
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    cli_path = repo_root / "tools" / "cad_agent" / "cad_agent_cli.py"

    spec = importlib.util.spec_from_file_location("cad_agent_cli", cli_path)
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)  # type: ignore[assignment]
    return m


class FakeClient:
    """Captures requests without making network calls."""

    def __init__(self):
        self.calls = []  # list[(method, path, payload)]

    def request(self, method: str, path: str, payload=None, json_body=None, **_kwargs):
        # The real ApiClient uses `json_body=`; accept both for convenience.
        if json_body is not None and payload is not None:
            raise AssertionError("Pass only one of payload or json_body")
        body = payload if json_body is None else json_body
        self.calls.append((method, path, body))

        # Mimic the HTTP codes the real API uses for these endpoints.
        status = 200
        if method == "POST" and path == "/v1/sessions":
            status = 201
        elif method == "POST" and path.startswith("/v1/sessions/") and path.endswith("/messages"):
            status = 202

        return status, {"ok": True, "method": method, "path": path, "payload": body}

    def get_json(self, path: str):
        code, body = self.request("GET", path, None)
        assert code == 200
        return body

    def post_json(self, path: str, payload):
        code, body = self.request("POST", path, payload)
        assert 200 <= code < 300
        return body


def _parse(cli, argv):
    parser = cli.build_parser()
    return parser.parse_args(argv)


def test_global_flags_parse(cli):
    args = _parse(cli, ["--base-url", "http://localhost:8081", "--timeout", "123", "--debug", "health"])
    assert args.base_url == "http://localhost:8081"
    assert args.timeout == 123
    assert args.debug is True
    assert args.cmd == "health"


def test_health_calls_endpoint(cli):
    args = _parse(cli, ["health"])
    c = FakeClient()
    rc = cli.cmd_health(c, args)
    assert rc == 0
    assert c.calls == [("GET", "/health", None)]


def test_session_create_payload(cli):
    args = _parse(cli, ["session", "create", "--title", "itest"])
    c = FakeClient()
    rc = cli.cmd_session_create(c, args)
    assert rc == 0
    method, path, payload = c.calls[0]
    assert method == "POST"
    assert path == "/v1/sessions"
    assert payload == {"title": "itest"}


def test_session_close_path(cli):
    args = _parse(cli, ["session", "close", "abc123"])
    c = FakeClient()
    rc = cli.cmd_session_close(c, args)
    assert rc == 0
    assert c.calls[0][0] == "POST"
    assert c.calls[0][1] == "/v1/sessions/abc123/close"


def test_message_send_parses_export_and_numbers(cli):
    args = _parse(
        cli,
        [
            "message",
            "send",
            "--session",
            "sid",
            "--prompt",
            "Create a box",
            "--export",
            "fcstd,step",
            "--units",
            "mm",
            "--tolerance-mm",
            "0.1",
            "--mode",
            "design",
            "--max-repair-iterations",
            "2",
        ],
    )

    c = FakeClient()
    rc = cli.cmd_message_send(c, args)
    assert rc == 0

    method, path, payload = c.calls[0]
    assert method == "POST"
    assert path == "/v1/sessions/sid/messages"
    assert payload["content"] == "Create a box"
    assert payload["mode"] == "design"
    assert payload["units"] == "mm"
    assert payload["tolerance_mm"] == 0.1
    assert payload["max_repair_iterations"] == 2
    assert payload["export"] == {"fcstd": True, "step": True, "stl": False}


def test_job_get_uses_positional_job_id(cli):
    args = _parse(cli, ["job", "get", "job-123"])
    c = FakeClient()
    rc = cli.cmd_job_get(c, args)
    assert rc == 0
    assert c.calls[0][0] == "GET"
    assert c.calls[0][1] == "/v1/jobs/job-123"


def test_job_wait_accepts_positional_and_aliases(cli, monkeypatch):
    # The CLI exposes global --timeout, and job wait exposes --max-wait-seconds.
    args = _parse(cli, ["--timeout", "7", "job", "wait", "job-999", "--max-wait-seconds", "5", "--poll-seconds", "1"])

    # Patch ApiClient.get_json calls inside cmd_job_wait via FakeClient
    c = FakeClient()

    # Make job status change from started -> finished
    states = [
        {"status": "queued"},
        {"status": "started"},
        {"status": "finished"},
    ]

    def fake_request(method, path, payload=None, json_body=None, **kwargs):
        assert method == "GET"
        assert path == "/v1/jobs/job-999"
        return 200, states.pop(0)

    monkeypatch.setattr(c, "request", fake_request)
    # Avoid sleeping in unit tests
    monkeypatch.setattr(cli.time, "sleep", lambda *_: None)

    rc = cli.cmd_job_wait(c, args)
    assert rc == 0
