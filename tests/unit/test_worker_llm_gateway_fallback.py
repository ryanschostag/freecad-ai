import importlib.util
import sys
from pathlib import Path

import pytest


class _FakeResponse:
    def __init__(self, payload, status_code=200, text=None):
        self._payload = payload
        self.status_code = status_code
        self.text = text if text is not None else (payload if isinstance(payload, str) else "")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._payload


def _load_llm_module():
    repo_root = Path(__file__).resolve().parents[2]
    worker_root = repo_root / "services" / "freecad-worker"
    if str(worker_root) not in sys.path:
        sys.path.insert(0, str(worker_root))
    module_path = worker_root / "worker" / "llm.py"
    spec = importlib.util.spec_from_file_location("worker_llm_gateway_fallback_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_candidate_base_urls_include_linux_gateway_after_host_gateway(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://freecad-ai-llm:8000")
    monkeypatch.setenv("LLM_BASE_URL", "http://freecad-ai-llm:8000")
    llm = _load_llm_module()
    monkeypatch.setattr(llm, "_linux_default_gateway_ip", lambda: "172.19.0.1")

    assert llm._candidate_base_urls("http://freecad-ai-llm:8000")[:4] == [
        "http://freecad-ai-llm:8000",
        "http://llm:8000",
        "http://host.docker.internal:8000",
        "http://172.19.0.1:8000",
    ]


def test_chat_falls_back_to_linux_gateway_when_host_docker_internal_is_unreachable(monkeypatch):
    llm = _load_llm_module()
    monkeypatch.setattr(llm, "_linux_default_gateway_ip", lambda: "172.19.0.1")

    class _FallbackClient:
        def __init__(self):
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json=None):
            self.calls.append((url, json))
            if url.startswith("http://freecad-ai-llm:8000"):
                raise llm.httpx.ConnectError("[Errno -2] Name or service not known")
            if url.startswith("http://llm:8000"):
                raise llm.httpx.ConnectError("[Errno -2] Name or service not known")
            if url.startswith("http://host.docker.internal:8000"):
                raise llm.httpx.ConnectError("[Errno 101] Network is unreachable")
            if url.startswith("http://172.19.0.1:8000") and url.endswith("/completion"):
                return _FakeResponse({"content": "READY"})
            if url.startswith("http://172.19.0.1:8000") and url.endswith("/v1/chat/completions"):
                return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})
            raise AssertionError(f"unexpected URL: {url}")

    fake = _FallbackClient()
    monkeypatch.setattr(llm.httpx, "Client", lambda timeout=None: fake)

    out = llm.chat([{"role": "user", "content": "hello"}], timeout_s=10, max_attempts=1)

    assert out == "ok"
    assert [call[0] for call in fake.calls[:5]] == [
        "http://freecad-ai-llm:8000/completion",
        "http://llm:8000/completion",
        "http://host.docker.internal:8000/completion",
        "http://172.19.0.1:8000/completion",
        "http://172.19.0.1:8000/v1/chat/completions",
    ]


def test_chat_reports_all_attempted_endpoints_when_every_candidate_fails(monkeypatch):
    llm = _load_llm_module()
    monkeypatch.setattr(llm, "_linux_default_gateway_ip", lambda: "172.19.0.1")

    class _AlwaysFailClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json=None):
            raise llm.httpx.ConnectError(f"cannot reach {url}")

    monkeypatch.setattr(llm.httpx, "Client", lambda timeout=None: _AlwaysFailClient())

    with pytest.raises(RuntimeError) as exc:
        llm.chat([{"role": "user", "content": "hello"}], timeout_s=10, max_attempts=1)

    message = str(exc.value)
    assert "All LLM endpoints failed:" in message
    assert "http://freecad-ai-llm:8000" in message
    assert "http://llm:8000" in message
    assert "http://host.docker.internal:8000" in message
    assert "http://172.19.0.1:8000" in message
