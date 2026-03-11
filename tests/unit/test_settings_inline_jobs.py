from app.settings import Settings


def test_settings_parses_inline_jobs_from_environment(monkeypatch):
    monkeypatch.setenv('CAD_AGENT_INLINE_JOBS', '1')
    assert Settings().inline_jobs is True
