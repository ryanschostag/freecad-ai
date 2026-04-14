from pathlib import Path


def test_test_profile_enables_inline_jobs_for_api_and_test_runner():
    compose = Path('docker-compose.yml').read_text(encoding='utf-8')
    assert 'api-test:' in compose
    assert 'test-runner:' in compose
    assert compose.count('CAD_AGENT_INLINE_JOBS=1') >= 2
