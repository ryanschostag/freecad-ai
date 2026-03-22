from pathlib import Path


def test_worker_main_waits_for_llm_before_starting_queue_worker():
    repo_root = Path(__file__).resolve().parents[2]
    source = (repo_root / "services" / "freecad-worker" / "worker" / "worker_main.py").read_text(encoding="utf-8")

    assert 'from worker.llm import wait_until_llm_ready' in source
    assert 'ready_url = wait_until_llm_ready()' in source
    assert 'print(f"LLM ready for worker startup: {ready_url}", flush=True)' in source
    assert source.index('ready_url = wait_until_llm_ready()') < source.index('redis = Redis.from_url(settings.redis_url)')
