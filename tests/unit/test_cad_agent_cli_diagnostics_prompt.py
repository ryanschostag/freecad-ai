from pathlib import Path
import importlib.util
import sys
import zipfile
import pytest


@pytest.fixture()
def cli(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    cli_path = repo_root / "tools" / "cad_agent" / "cad_agent_cli.py"
    spec = importlib.util.spec_from_file_location("cad_agent_cli_diag_prompt", cli_path)
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)  # type: ignore[assignment]
    return m


def test_extract_prompt_and_config_from_logs(cli):
    logs = {
        "events": [
            {
                "type": "message.user",
                "payload": {
                    "message_id": "m1",
                    "mode": "design",
                    "prompt": "make a razor",
                    "export": {"fcstd": True, "step": True, "stl": False},
                    "units": "mm",
                    "tolerance_mm": 0.1,
                    "timeout_seconds": 72000,
                },
            }
        ]
    }
    prompt, cfg = cli._extract_prompt_and_config_from_logs(logs)
    assert prompt == "make a razor"
    assert cfg["mode"] == "design"
    assert cfg["units"] == "mm"
    assert cfg["timeout_seconds"] == 72000


def test_job_diagnose_writes_prompt_and_request_config(cli, tmp_path, monkeypatch):
    class Client:
        base_url = "http://localhost:8080"
        def request(self, method, path, payload=None, json_body=None, **kwargs):
            if method == "GET" and path == "/v1/jobs/job-1":
                return 200, {"job_id": "job-1", "session_id": "sid-1", "status": "queued"}
            if method == "GET" and path == "/v1/sessions/sid-1/logs":
                return 200, {"events": [{"type": "message.user", "payload": {"prompt": "make a razor", "mode": "design", "units": "mm", "tolerance_mm": 0.1}}]}
            if method == "GET" and path == "/v1/sessions/sid-1/artifacts":
                return 200, {"artifacts": []}
            raise AssertionError((method, path))
        def download_to(self, url, out_path: Path):
            raise AssertionError("should not download")

    monkeypatch.setattr(cli, "_collect_docker_logs", lambda bundle_dir: [])
    monkeypatch.setattr(cli, "_copy_sanitized_configs", lambda bundle_dir: [])
    out_zip = tmp_path / "diag.zip"
    rc = cli.cmd_job_diagnose(Client(), cli.argparse.Namespace(job_id="job-1", session_id="sid-1", out=str(out_zip)))
    assert rc == 0
    with zipfile.ZipFile(out_zip) as zf:
        assert "prompt.txt" in zf.namelist()
        assert "request_config.json" in zf.namelist()
        assert zf.read("prompt.txt").decode().strip() == "make a razor"
