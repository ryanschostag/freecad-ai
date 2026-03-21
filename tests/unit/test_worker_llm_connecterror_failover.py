import importlib.util
import sys
from pathlib import Path


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
    spec = importlib.util.spec_from_file_location("worker_llm_connecterror_failover_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_connect_error_during_warmup_fails_over_to_next_base_url(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://llm:8000")
    llm = _load_llm_module()

    class _FallbackClient:
        def __init__(self):
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json=None):
            self.calls.append((url, json))
            if url.startswith("http://llm:8000"):
                raise llm.httpx.ConnectError("[Errno -2] Name or service not known")
            if url.endswith("/completion"):
                return _FakeResponse({"content": "READY"})
            if url.endswith("/v1/chat/completions"):
                return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})
            raise AssertionError(f"unexpected URL: {url}")

    fake = _FallbackClient()
    monkeypatch.setattr(llm.httpx, "Client", lambda timeout=None: fake)

    out = llm.chat([{"role": "user", "content": "hello"}], timeout_s=10, max_attempts=1)

    assert out == "ok"
    attempted_urls = [call[0] for call in fake.calls]
    assert attempted_urls[-2:] == [
        "http://freecad-ai-llm:8000/completion",
        "http://freecad-ai-llm:8000/v1/chat/completions",
    ]
