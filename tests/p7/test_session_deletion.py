"""Deletion removes presentation state without resetting budgets or the security audit."""

from concurrent.futures import ThreadPoolExecutor

import pytest

pytestmark = pytest.mark.p7


@pytest.fixture
def settings(tmp_path):
    from agentguard_demo.settings import DemoSettings

    root = tmp_path / "sandbox"
    (root / "input").mkdir(parents=True)
    (root / "input" / "hello.txt").write_text("public fixture", encoding="utf-8")
    return DemoSettings(enable_protection=True, sandbox_root=root)


@pytest.fixture
def client(settings):
    from agentguard_demo.api import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app(settings)) as connection:
        yield connection


def sid(client):
    response = client.post("/sessions")
    assert response.status_code == 201
    return response.json()["session_id"]


def chat(client, session, message):
    response = client.post(f"/sessions/{session}/chat", json={"message": message})
    assert response.status_code == 200
    return response.json()["events"]


def test_delete_removes_history_but_keeps_core_audit_and_shared_budget(client):
    session = sid(client)
    other = sid(client)
    chat(client, session, 'read_file {"path":"hello.txt"}')
    service = client.app.state.chat
    old = service.get_session(session)
    audit = service.audit.records()
    used = service.total_provider_calls
    assert audit
    assert client.delete(f"/sessions/{session}").status_code == 204
    assert service.get_session(session) is None
    assert old.deleted and not old.messages and old.guard is None
    assert service.total_provider_calls == used
    assert service.audit.records() == audit
    assert client.get(f"/sessions/{session}/history").status_code == 404
    assert client.get(f"/sessions/{session}/audit").status_code == 404
    assert client.post(f"/sessions/{session}/chat", json={"message": "hello"}).status_code == 404
    assert client.delete(f"/sessions/{session}").status_code == 404
    assert [s["session_id"] for s in client.get("/sessions").json()["sessions"]] == [other]
    assert service.audit.history.events(session) == []


def test_busy_session_cannot_be_deleted_and_stale_stream_cannot_execute(client):
    session = sid(client)
    service = client.app.state.chat
    old = service.get_session(session)
    queued = service.client_events(old, 'write_note {"name":"never.txt","content":"x"}')
    with old.presentation_lock:
        assert client.delete(f"/sessions/{session}").status_code == 409
        assert service.audit.history.exists(session)
    assert client.delete(f"/sessions/{session}").status_code == 204
    assert list(queued) == []
    assert service.total_provider_calls == 0
    assert not list(service.settings.sandbox_root.rglob("never.txt"))


def test_delete_archived_session_survives_restart(settings):
    from agentguard_demo.api import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app(settings)) as first:
        session = sid(first)
        chat(first, session, "hello")
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get("/sessions").json()["sessions"][0]["active"] is False
        assert restarted.delete(f"/sessions/{session}").status_code == 204
    with TestClient(create_app(settings)) as again:
        assert again.get("/sessions").json()["sessions"] == []


@pytest.mark.parametrize("origin", ["https://example.invalid", "null"])
def test_cross_origin_delete_denied(client, origin):
    session = sid(client)
    assert client.delete(f"/sessions/{session}", headers={"Origin": origin}).status_code == 403
    assert client.get(f"/sessions/{session}/history").status_code == 200


def test_simultaneous_deletes_cannot_reactivate_session(client):
    session = sid(client)
    with ThreadPoolExecutor(2) as pool:
        results = list(
            pool.map(lambda _: client.delete(f"/sessions/{session}").status_code, range(2))
        )
    assert results.count(204) == 1
    assert all(code in {204, 404, 409} for code in results)
    assert client.get("/sessions").json()["sessions"] == []
