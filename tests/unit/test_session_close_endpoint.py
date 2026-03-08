from pathlib import Path


def test_end_session_route_exists_and_closes_session():
    source = Path("services/api/app/routes/sessions.py").read_text()

    assert '@router.post("/sessions/{session_id}/end")' in source
    assert 'session.status = "closed"' in source
    assert 'session.closed_at = now' in source
    assert 'type="session.closed"' in source


def test_send_message_rejects_closed_sessions():
    source = Path("services/api/app/routes/sessions.py").read_text()

    assert 'if session.status != "active":' in source
    assert 'raise HTTPException(status_code=409, detail="session is not active")' in source
