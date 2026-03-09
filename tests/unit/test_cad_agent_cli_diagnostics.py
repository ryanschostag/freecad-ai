from pathlib import Path

import pytest
import requests


@pytest.fixture()
def cli(tmp_path):
    import importlib.util
    import sys

    repo_root = Path(__file__).resolve().parents[2]
    cli_path = repo_root / "tools" / "cad_agent" / "cad_agent_cli.py"
    spec = importlib.util.spec_from_file_location("cad_agent_cli_diag", cli_path)
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)  # type: ignore[assignment]
    return m


class FakeClient:
    def __init__(self, base_url: str = "http://localhost:8080"):
        self.base_url = base_url
        self.calls = []
        self.download_attempts = []

    def request(self, method: str, path: str, payload=None, json_body=None, **_kwargs):
        self.calls.append((method, path))
        if method == "GET" and path == "/v1/jobs/job-1":
            return 200, {"job_id": "job-1", "session_id": "sid-1", "status": "finished"}
        if method == "GET" and path == "/v1/sessions/sid-1/logs":
            return 200, {"events": [{"kind": "job.completed"}]}
        if method == "GET" and path == "/v1/sessions/sid-1/artifacts":
            return 200, {"artifacts": [{"artifact_id": "art-1"}]}
        if method == "GET" and path == "/v1/artifacts/art-1":
            return 200, {
                "artifact_id": "art-1",
                "kind": "freecad_macro_py",
                "object_key": "sessions/sid-1/macros/test.py",
                "download_url": "http://minio:9000/cad-artifacts/sessions/sid-1/macros/test.py?sig=abc",
                "proxy_download_url": "/v1/artifacts/art-1/content",
            }
        raise AssertionError(f"unexpected request: {method} {path}")

    def download_to(self, url: str, out_path: Path):
        self.download_attempts.append(url)
        if url.startswith("http://minio:9000/"):
            raise requests.ConnectionError("host not reachable")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("artifact-data\n", encoding="utf-8")


def test_candidate_download_urls_rewrites_internal_minio_host(cli):
    urls = cli._candidate_download_urls(
        "http://localhost:8080",
        "http://minio:9000/cad-artifacts/foo.txt?sig=1",
    )
    assert urls[0] == "http://minio:9000/cad-artifacts/foo.txt?sig=1"
    assert "http://localhost:9000/cad-artifacts/foo.txt?sig=1" in urls
    assert "http://127.0.0.1:9000/cad-artifacts/foo.txt?sig=1" in urls


def test_job_diagnose_rewrites_internal_artifact_url_and_creates_zip(cli, tmp_path, monkeypatch):
    client = FakeClient()
    out_zip = tmp_path / "diag.zip"

    monkeypatch.setattr(cli, "_collect_docker_logs", lambda bundle_dir: [])
    monkeypatch.setattr(cli, "_copy_sanitized_configs", lambda bundle_dir: [])

    args = cli.argparse.Namespace(job_id="job-1", session_id="sid-1", out=str(out_zip))
    rc = cli.cmd_job_diagnose(client, args)

    assert rc == 0
    assert out_zip.exists()
    assert client.download_attempts[0].startswith("http://minio:9000/")
    assert any(url.startswith("http://localhost:9000/") for url in client.download_attempts)


def test_download_session_artifacts_records_failure_without_crashing(cli, tmp_path):
    class AlwaysFailClient(FakeClient):
        def download_to(self, url: str, out_path: Path):
            self.download_attempts.append(url)
            raise requests.ConnectionError("still unreachable")

    client = AlwaysFailClient()
    manifest = cli._download_session_artifacts(client, "sid-1", tmp_path)
    assert manifest["downloaded"][0]["status"] == "download_failed"
    assert manifest["downloaded"][0]["artifact_id"] == "art-1"


def test_download_session_artifacts_uses_api_proxy_after_presigned_url_failure(cli, tmp_path):
    class ProxyClient(FakeClient):
        def download_to(self, url: str, out_path: Path):
            self.download_attempts.append(url)
            if url != "http://localhost:8080/v1/artifacts/art-1/content":
                raise requests.HTTPError("403 forbidden")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text("artifact-from-proxy\n", encoding="utf-8")

    client = ProxyClient()
    manifest = cli._download_session_artifacts(client, "sid-1", tmp_path)

    assert manifest["downloaded"][0]["download_url"] == "http://localhost:8080/v1/artifacts/art-1/content"
    assert (tmp_path / "001_freecad_macro_py_art-1.py").read_text(encoding="utf-8") == "artifact-from-proxy\n"
