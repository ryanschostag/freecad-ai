import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException


class _FakeWorkerRegistry:
    workers = []

    @classmethod
    def all(cls, connection=None):
        return list(cls.workers)


class _FakeQueue:
    def __init__(self, name="freecad", connection="redis-conn"):
        self.name = name
        self.connection = connection


class _FakeWorker:
    def __init__(self, name: str, queue_names, last_heartbeat):
        self.name = name
        self.queue_names = list(queue_names)
        self.last_heartbeat = last_heartbeat


class _FakeResp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


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
                return item if isinstance(item, _FakeResp) else _FakeResp(item)

        return _Client()


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

    rq_mod = types.ModuleType("rq")
    rq_mod.Worker = _FakeWorkerRegistry
    sys.modules.setdefault("rq", rq_mod)

    app_pkg = types.ModuleType("app")
    models_mod = types.ModuleType("app.models")
    db_mod = types.ModuleType("app.db")
    db_mod.get_db = lambda: None
    queue_mod = types.ModuleType("app.queue")
    queue_mod.get_queue = lambda *args, **kwargs: _FakeQueue()
    schemas_mod = types.ModuleType("app.schemas")
    schemas_mod.CreateSessionRequest = object
    settings_mod = types.ModuleType("app.settings")

    class _Settings:
        llm_base_url = "http://llm:8000"
        llm_health_timeout_seconds = 2.0
        llm_ready_timeout_seconds = 300.0
        queue_worker_heartbeat_timeout_seconds = 120.0
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
    spec = importlib.util.spec_from_file_location("sessions_route_queue_worker_ready_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.anyio
async def test_ensure_queue_worker_ready_accepts_recent_worker(monkeypatch):
    sessions = _load_sessions_module()
    now = datetime.now(timezone.utc)
    _FakeWorkerRegistry.workers = [
        _FakeWorker("worker-1", ["freecad"], now - timedelta(seconds=15)),
    ]

    await sessions.ensure_queue_worker_ready()


@pytest.mark.anyio
async def test_ensure_queue_worker_ready_rejects_stale_or_missing_worker(monkeypatch):
    sessions = _load_sessions_module()
    now = datetime.now(timezone.utc)
    _FakeWorkerRegistry.workers = [
        _FakeWorker("worker-1", ["freecad"], now - timedelta(seconds=999)),
    ]

    with pytest.raises(HTTPException) as excinfo:
        await sessions.ensure_queue_worker_ready()

    detail = str(excinfo.value.detail)
    assert excinfo.value.status_code == 503
    assert "No live queue worker is available for 'freecad'" in detail
    assert "worker-1" in detail
    assert "stale" in detail
