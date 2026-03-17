from pathlib import Path


def test_send_message_does_not_gate_job_id_creation_on_llm_readiness():
    repo_root = Path(__file__).resolve().parents[2]
    sessions_py = (repo_root / "services" / "api" / "app" / "routes" / "sessions.py").read_text(encoding="utf-8")

    send_message_block = sessions_py.split('@router.post("/sessions/{session_id}/messages", status_code=202)')[1]
    assert 'await ensure_llm_ready()' not in send_message_block
    assert 'Queue the\n    # job immediately so the UI always receives a job id' in send_message_block
