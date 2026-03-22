import importlib.util
import sys
from pathlib import Path

import pytest


class _FakeWorkerRegistry:
    @classmethod
    def all(cls, connection=None):
        raise AssertionError("worker registry should not be queried when inline bypass is enabled")


class _FakeQueue:
    def __init__(self, name="freecad", connection="redis-conn"):
        self.name = name
        self.connection = connection


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
    sys.modules["rq"] = rq_mod

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
        inline_jobs = True

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
    spec = importlib.util.spec_from_file_location("sessions_route_queue_worker_inline_bypass_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_send_message_path_still_calls_worker_gate_before_enqueue():
    repo_root = Path(__file__).resolve().parents[2]
    sessions_py = (repo_root / "services" / "api" / "app" / "routes" / "sessions.py").read_text(encoding="utf-8")
    send_message_block = sessions_py.split('@router.post("/sessions/{session_id}/messages", status_code=202)')[1]
    assert 'await ensure_queue_worker_ready()' in send_message_block
    assert '_QUEUE_WORKER_READY_ALLOW_INLINE_BYPASS.set(True)' in send_message_block


@pytest.mark.anyio
async def test_ensure_queue_worker_ready_only_bypasses_when_context_is_enabled():
    sessions = _load_sessions_module()

    with pytest.raises(Exception) as excinfo:
        await sessions.ensure_queue_worker_ready()
    assert "worker registry should not be queried" in str(excinfo.value)

    token = sessions._QUEUE_WORKER_READY_ALLOW_INLINE_BYPASS.set(True)
    try:
        await sessions.ensure_queue_worker_ready()
    finally:
        sessions._QUEUE_WORKER_READY_ALLOW_INLINE_BYPASS.reset(token)
