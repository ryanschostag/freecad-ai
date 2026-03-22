from pathlib import Path


def test_send_message_gates_enqueue_on_live_worker_readiness():
    repo_root = Path(__file__).resolve().parents[2]
    sessions_py = (repo_root / "services" / "api" / "app" / "routes" / "sessions.py").read_text(encoding="utf-8")

    send_message_block = sessions_py.split('@router.post("/sessions/{session_id}/messages", status_code=202)')[1]
    assert 'await ensure_queue_worker_ready()' in send_message_block
    assert send_message_block.index('await ensure_queue_worker_ready()') < send_message_block.index('q.enqueue_call(')
