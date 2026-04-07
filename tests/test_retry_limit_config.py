from __future__ import annotations

import importlib
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER_ROOT = REPO_ROOT / 'services' / 'freecad-worker'
for path in (REPO_ROOT, WORKER_ROOT):
    s = str(path)
    if s not in sys.path:
        sys.path.insert(0, s)


def test_env_sample_exposes_retry_limit():
    env_text = (REPO_ROOT / '.env.sample').read_text(encoding='utf-8')
    assert 'LLM_ERROR_RETRY_LIMIT=3' in env_text


def test_docker_compose_wires_retry_limit():
    compose_text = (REPO_ROOT / 'docker-compose.yml').read_text(encoding='utf-8')
    assert 'LLM_ERROR_RETRY_LIMIT=${LLM_ERROR_RETRY_LIMIT:-3}' in compose_text


def test_api_sessions_route_uses_configured_retry_limit():
    source = (REPO_ROOT / 'services' / 'api' / 'app' / 'routes' / 'sessions.py').read_text(encoding='utf-8')
    assert 'settings.llm_error_retry_limit' in source
    assert 'max_repair_iterations=max(1, int(settings.llm_error_retry_limit))' in source


def test_worker_jobs_falls_back_to_configured_retry_limit():
    source = (REPO_ROOT / 'services' / 'freecad-worker' / 'worker' / 'jobs.py').read_text(encoding='utf-8')
    assert 'configured_retry_limit = max(1, int(settings.llm_error_retry_limit))' in source
    assert 'max_repair_iterations if max_repair_iterations is not None else configured_retry_limit' in source


def test_worker_settings_reads_retry_limit(monkeypatch):
    monkeypatch.setenv('LLM_ERROR_RETRY_LIMIT', '7')
    import worker.settings as worker_settings
    reloaded = importlib.reload(worker_settings)
    assert reloaded.settings.llm_error_retry_limit == 7


def test_worker_settings_clamps_invalid_retry_limit(monkeypatch):
    monkeypatch.setenv('LLM_ERROR_RETRY_LIMIT', '0')
    import worker.settings as worker_settings
    reloaded = importlib.reload(worker_settings)
    assert reloaded.settings.llm_error_retry_limit == 1
