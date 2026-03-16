import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException


def _load_sessions_module():
    repo_root = Path(__file__).resolve().parents[2]
    api_root = repo_root / "services" / "api"
    if str(api_root) not in sys.path:
        sys.path.insert(0, str(api_root))

    import types

    sqlalchemy = types.ModuleType("sqlalchemy")
    sqlalchemy_orm = types.ModuleType("sqlalchemy.orm")
    sqlalchemy_orm.Session = object
    sqlalchemy.orm = sqlalchemy_orm
    sys.modules.setdefault("sqlalchemy", sqlalchemy)
    sys.modules.setdefault("sqlalchemy.orm", sqlalchemy_orm)

    app_pkg = types.ModuleType("app")
    models_mod = types.ModuleType("app.models")
    db_mod = types.ModuleType("app.db")
    db_mod.get_db = lambda: None
    queue_mod = types.ModuleType("app.queue")
    queue_mod.get_queue = lambda *args, **kwargs: None
    schemas_mod = types.ModuleType("app.schemas")
    schemas_mod.CreateSessionRequest = object
    settings_mod = types.ModuleType("app.settings")

    class _Settings:
        llm_base_url = "http://llm:8000"
        default_job_timeout_seconds = 300
        job_timeout_buffer_seconds = 30
        inline_jobs = False

    settings_mod.Settings = _Settings
    utils_mod = types.ModuleType("app.utils")
    utils_mod.upsert_time = lambda *args, **kwargs: None

    app_pkg.models = models_mod
    sys.modules.setdefault("app", app_pkg)
    sys.modules.setdefault("app.models", models_mod)
    sys.modules.setdefault("app.db", db_mod)
    sys.modules.setdefault("app.queue", queue_mod)
    sys.modules.setdefault("app.schemas", schemas_mod)
    sys.modules.setdefault("app.settings", settings_mod)
    sys.modules.setdefault("app.utils", utils_mod)

    module_path = api_root / "app" / "routes" / "sessions.py"
    spec = importlib.util.spec_from_file_location("sessions_route_llm_ready_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Resp:
    def __init__(self, status_code: int):
        self.status_code = status_code


class _ClientFactory:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, *args, **kwargs):
        outer = self

        class _Client:
            async def __aenter__(self_inner):
                return self_inner

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

            async def get(self_inner, url):
                outer.calls.append(url)
                item = outer.outcomes.pop(0)
                if isinstance(item, Exception):
                    raise item
                return _Resp(item)

        return _Client()


@pytest.mark.anyio
async def test_ensure_llm_ready_retries_until_success(monkeypatch):
    sessions = _load_sessions_module()

    class _Settings:
        llm_base_url = "http://llm:8000"

    monkeypatch.setattr(sessions, "Settings", lambda: _Settings())
    factory = _ClientFactory([
        Exception("not ready"), Exception("not ready"), Exception("not ready"), 200,
    ])
    monkeypatch.setattr(sessions.httpx, "AsyncClient", factory)

    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    class _Loop:
        def __init__(self):
            self.current = 0.0

        def time(self):
            self.current += 1.0
            return self.current

    monkeypatch.setattr(sessions.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(sessions.asyncio, "get_running_loop", lambda: _Loop())

    await sessions.ensure_llm_ready(max_wait_s=5.0)

    assert sleep_calls == [1.0]
    assert factory.calls[0] == "http://llm:8000/health"
    assert factory.calls[-1] == "http://llm:8000/health"


@pytest.mark.anyio
async def test_ensure_llm_ready_raises_after_retry_window(monkeypatch):
    sessions = _load_sessions_module()

    class _Settings:
        llm_base_url = "http://llm:8000"

    monkeypatch.setattr(sessions, "Settings", lambda: _Settings())
    factory = _ClientFactory([
        Exception("down"), Exception("down"), Exception("down"),
        Exception("down"), Exception("down"), Exception("down"),
    ])
    monkeypatch.setattr(sessions.httpx, "AsyncClient", factory)

    async def fake_sleep(seconds):
        return None

    class _Loop:
        def __init__(self):
            self.current = 0.0

        def time(self):
            self.current += 10.0
            return self.current

    monkeypatch.setattr(sessions.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(sessions.asyncio, "get_running_loop", lambda: _Loop())

    with pytest.raises(HTTPException) as excinfo:
        await sessions.ensure_llm_ready(max_wait_s=5.0)

    assert excinfo.value.status_code == 503
    assert "LLM is not ready at http://llm:8000" in excinfo.value.detail
