import importlib.util
import sys
from pathlib import Path


class _FakeResponse:
    def __init__(self, payload, status_code=200, text: str | None = None):
        self._payload = payload
        self.status_code = status_code
        self.text = text if text is not None else (payload if isinstance(payload, str) else "")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, json=None):
        self.calls.append((url, json))
        if not self._responses:
            raise AssertionError("unexpected extra POST")
        return self._responses.pop(0)


def _load_llm_module():
    repo_root = Path(__file__).resolve().parents[2]
    worker_root = repo_root / "services" / "freecad-worker"
    if str(worker_root) not in sys.path:
        sys.path.insert(0, str(worker_root))
    module_path = worker_root / "worker" / "llm.py"
    spec = importlib.util.spec_from_file_location("worker_llm_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[assignment]
    return module


def test_chat_extracts_text_from_content_parts(monkeypatch):
    llm = _load_llm_module()

    fake = _FakeClient([
        _FakeResponse({"content": "READY"}),
        _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": [
                                {"type": "text", "text": "```python\n"},
                                {"type": "text", "text": "import FreeCAD as App\n"},
                                {"type": "text", "text": "App.newDocument('Model')\n```"},
                            ]
                        }
                    }
                ]
            }
        )
    ])
    monkeypatch.setattr(llm.httpx, "Client", lambda timeout=None: fake)

    out = llm.chat([{"role": "user", "content": "make a box"}])

    assert "```" not in out
    assert "import FreeCAD as App" in out
    assert fake.calls[0][0].endswith("/completion")
    assert fake.calls[1][0].endswith("/v1/chat/completions")


def test_chat_falls_back_to_completion_when_chat_payload_has_no_extractable_text(monkeypatch):
    llm = _load_llm_module()

    fake = _FakeClient([
        _FakeResponse({"content": "READY"}),
        _FakeResponse({"choices": [{"message": {"content": [{"type": "image", "image_url": "x"}]}}]}),
        _FakeResponse({"content": "import FreeCAD as App\nApp.newDocument('Model')\n"}),
    ])
    monkeypatch.setattr(llm.httpx, "Client", lambda timeout=None: fake)

    out = llm.chat([{"role": "user", "content": "make a box"}])

    assert "App.newDocument('Model')" in out
    assert fake.calls[2][0].endswith("/completion")


def test_chat_sanitizes_markdown_fence_stop_sequence(monkeypatch):
    llm = _load_llm_module()

    fake = _FakeClient([
        _FakeResponse({"content": "READY"}),
        _FakeResponse({
            "choices": [
                {
                    "message": {
                        "content": "```python\nimport FreeCAD as App\nApp.newDocument('Model')\n```"
                    }
                }
            ]
        })
    ])
    monkeypatch.setattr(llm.httpx, "Client", lambda timeout=None: fake)

    out = llm.chat(
        [{"role": "user", "content": "make a box"}],
        stop=["<|im_end|>", "</s>", "```"],
    )

    payload = fake.calls[1][1]
    assert payload["stop"] == ["<|im_end|>", "</s>"]
    assert out == "import FreeCAD as App\nApp.newDocument('Model')"


def test_chat_waits_for_inference_warmup_before_chat_completion(monkeypatch):
    llm = _load_llm_module()

    fake = _FakeClient([
        _FakeResponse({"error": "loading model"}, status_code=503, text="loading model"),
        _FakeResponse({"content": "READY"}),
        _FakeResponse({"choices": [{"message": {"content": "ok"}}]}),
    ])
    monkeypatch.setattr(llm.httpx, "Client", lambda timeout=None: fake)
    sleep_calls: list[float] = []
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    out = llm.chat([{"role": "user", "content": "hello"}], timeout_s=10, max_attempts=1)

    assert out == "ok"
    assert sleep_calls == [1.0]
    assert fake.calls[0][0].endswith("/completion")
    assert fake.calls[1][0].endswith("/completion")
    assert fake.calls[2][0].endswith("/v1/chat/completions")
