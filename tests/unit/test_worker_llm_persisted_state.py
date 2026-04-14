import importlib.util
import sys
from pathlib import Path


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

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
        return self._responses.pop(0)


def _load_llm_module():
    repo_root = Path(__file__).resolve().parents[2]
    worker_root = repo_root / "services" / "freecad-worker"
    if str(worker_root) not in sys.path:
        sys.path.insert(0, str(worker_root))
    module_path = worker_root / "worker" / "llm.py"
    spec = importlib.util.spec_from_file_location("worker_llm_state_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[assignment]
    return module


def test_chat_injects_persisted_training_profile(monkeypatch):
    llm = _load_llm_module()
    fake = _FakeClient([
        _FakeResponse({"choices": [{"message": {"content": "import FreeCAD as App\nApp.newDocument('Model')"}}]})
    ])
    monkeypatch.setattr(llm.httpx, "Client", lambda timeout=None: fake)
    monkeypatch.setattr(
        llm,
        "load_latest_snapshot",
        lambda _path: type(
            "Snapshot",
            (),
            {
                "inference_profile": {
                    "system_message": "Use the persisted training profile.",
                    "examples": [{"prompt": "make a box", "response": "Create Part::Box."}],
                    "retrieval_snippets": ["Prefer STEP export."],
                }
            },
        )(),
    )

    llm.chat([{"role": "user", "content": "make a box"}])

    payload = fake.calls[0][1]
    assert payload["messages"][0]["role"] == "system"
    assert "Persisted training examples" in payload["messages"][0]["content"]
    assert "Prefer STEP export." in payload["messages"][0]["content"]
