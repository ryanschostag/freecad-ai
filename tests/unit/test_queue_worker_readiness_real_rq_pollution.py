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


class _FakeRQWorker:
    @classmethod
    def all(cls, connection=None):
        raise ValueError('"Queue" or "connection" argument is required')


class _FakeWorker:
    def __init__(self, name: str, queue_names, last_heartbeat):
        self.name = name
        self.queue_names = list(queue_names)
        self.last_heartbeat = last_heartbeat


def _load_sessions_module_with_rq_already_present():
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

    rq_realish_mod = types.ModuleType("rq")
    rq_realish_mod.Worker = _FakeRQWorker
    sys.modules["rq"] = rq_realish_mod

    rq_mod = types.ModuleType("rq")
    rq_mod.Worker = _FakeWorkerRegistry
    sys.modules.setdefault("rq", rq_mod)

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
    sys.modules["app"] = app_pkg
    sys.modules["app.models"] = models_mod
    sys.modules["app.db"] = db_mod
    sys.modules["app.queue"] = queue_mod
    sys.modules["app.schemas"] = schemas_mod
    sys.modules["app.settings"] = settings_mod
    sys.modules["app.utils"] = utils_mod

    module_path = api_root / "app" / "routes" / "sessions.py"
    spec = importlib.util.spec_from_file_location("sessions_route_real_rq_pollution_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.anyio
async def test_queue_worker_readiness_falls_back_to_current_test_registry_when_rq_is_already_present():
    sessions = _load_sessions_module_with_rq_already_present()
    now = datetime.now(timezone.utc)
    _FakeWorkerRegistry.workers = [
        _FakeWorker("worker-1", ["freecad"], now - timedelta(seconds=5)),
    ]

    await sessions.ensure_queue_worker_ready()


@pytest.mark.anyio
async def test_queue_worker_readiness_reports_stale_current_test_registry_when_rq_is_already_present():
    sessions = _load_sessions_module_with_rq_already_present()
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
