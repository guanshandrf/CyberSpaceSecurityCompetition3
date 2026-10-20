import json

import pytest

pytestmark = pytest.mark.p1


def test_runtime_socketpair_ipc_works_while_ordinary_network_is_denied():
    import socket

    first, second = socket.socketpair()
    with first, second:
        first.sendall(b"local-ipc")
        assert second.recv(9) == b"local-ipc"
    with socket.socket() as connection:
        with pytest.raises(RuntimeError, match="forbid network"):
            connection.connect(("127.0.0.1", 443))


def create_session(client):
    response = client.post("/sessions")
    assert response.status_code == 201
    assert response.json()["mode"] == "unprotected"
    return response.json()["session_id"]


def chat(client, session, text):
    response = client.post(f"/sessions/{session}/chat", json={"message": text})
    assert response.status_code == 200
    return response.json()["events"]


def test_two_turn_conversation_retains_history_and_other_session_is_isolated(demo_client):
    session = create_session(demo_client)
    first = chat(demo_client, session, "记住本轮的蓝色笔记")
    assert first[0]["data"]["session_id"] == session
    assert first[-1]["data"]["ok"] is True
    second = chat(demo_client, session, "recall")
    assert second[-2]["data"]["content"] == "记住本轮的蓝色笔记"
    assert second[0]["data"]["turn"] == 2
    other = create_session(demo_client)
    assert chat(demo_client, other, "recall")[-2]["data"]["content"] == "无上一轮消息。"
    assert demo_client.get(f"/sessions/{session}").json()["provider_calls"] == 2


def test_json_chat_runs_real_langgraph_read_tool_and_correlates_events(demo_client, demo_settings):
    source = demo_settings.sandbox_root / "input"
    source.mkdir(parents=True)
    (source / "hello.txt").write_text("离线样例", encoding="utf-8")
    session = create_session(demo_client)
    events = chat(demo_client, session, 'read_file {"path":"hello.txt"}')
    assert [item["event"] for item in events] == [
        "session",
        "tool_call",
        "tool_result",
        "message",
        "done",
    ]
    assert events[1]["data"]["name"] == "read_file"
    assert events[2]["data"]["tool_call_id"] == events[1]["data"]["tool_call_id"]
    assert events[2]["data"]["result"] == {"ok": True, "content": "离线样例"}
    assert len({item["data"]["trace_id"] for item in events}) == 1
    assert demo_client.get(f"/sessions/{session}").json()["provider_calls"] == 2


def test_sse_runs_write_tool_and_streams_actual_correlated_session_events(
    demo_client, demo_settings
):
    session = create_session(demo_client)
    with demo_client.stream(
        "POST",
        f"/sessions/{session}/stream",
        json={
            "message": 'write_note {"name":"first.txt","content":"第一条\\n第二条"}',
        },
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        text = response.read().decode("utf-8")
    events = []
    for frame in text.strip().split("\n\n"):
        event, data = frame.split("\n", 1)
        events.append(
            {
                "event": event.removeprefix("event: "),
                "data": json.loads(data.removeprefix("data: ")),
            }
        )
    assert [item["event"] for item in events] == [
        "session",
        "tool_call",
        "tool_result",
        "message",
        "done",
    ]
    assert all(item["data"]["session_id"] == session for item in events)
    assert events[1]["data"]["tool_call_id"] == events[2]["data"]["tool_call_id"]
    note = demo_settings.sandbox_root / "notes" / session / "first.txt"
    assert note.read_text(encoding="utf-8") == "第一条\n第二条"
    assert events[2]["data"]["result"]["ok"] is True
    assert events[-1]["data"]["ok"] is True


def test_tool_error_is_structured_and_does_not_write_outside_sandbox(demo_client, demo_settings):
    session = create_session(demo_client)
    events = chat(demo_client, session, 'write_note {"name":"../escape.txt","content":"x"}')
    assert events[2]["data"]["result"] == {"ok": False, "error": "tool_error"}
    assert not (demo_settings.sandbox_root / "notes" / "escape.txt").exists()
    assert events[-1]["data"]["ok"] is True  # Turn completed; the tool itself reported failure.


def test_default_baseline_is_disabled_and_health_does_not_claim_guard(tmp_path):
    from agentguard_demo.api import create_app
    from agentguard_demo.settings import DemoSettings
    from fastapi.testclient import TestClient

    root = tmp_path / "disabled"
    with TestClient(create_app(DemoSettings(sandbox_root=root))) as client:
        assert client.get("/health").json() == {
            "baseline_enabled": False,
            "guard": "not_implemented",
        }
        assert client.post("/sessions").status_code == 503
        assert client.post("/sessions/x/chat", json={"message": "hello"}).status_code == 503
    assert not root.exists()


@pytest.mark.parametrize(
    "body",
    [
        {"message": ""},
        {"message": 42},
        {"message": "x" * 4097},
        {"message": "hello", "api_key": "synthetic-value"},
        {"message": "hello", "enable_baseline": True},
    ],
)
def test_chat_rejects_invalid_input_and_client_side_configuration(demo_client, body):
    session = create_session(demo_client)
    response = demo_client.post(f"/sessions/{session}/chat", json=body)
    assert response.status_code == 422
    assert "synthetic-value" not in response.text
    assert demo_client.get(f"/sessions/{session}").json()["provider_calls"] == 0


@pytest.mark.parametrize("route", ["chat", "stream"])
def test_unknown_session_is_http_404_before_streaming_starts(demo_client, route):
    assert (
        demo_client.post(f"/sessions/missing/{route}", json={"message": "hello"}).status_code == 404
    )


def test_provider_limit_returns_error_without_additional_model_or_tool_calls(demo_settings):
    from agentguard_demo.api import create_app
    from fastapi.testclient import TestClient

    settings = demo_settings.model_copy(update={"max_provider_calls": 1})
    with TestClient(create_app(settings)) as client:
        session = create_session(client)
        assert chat(client, session, "one")[-1]["data"]["ok"] is True
        events = chat(client, session, 'write_note {"name":"never.txt","content":"x"}')
        assert events[-2]["data"]["code"] == "provider_call_limit"
        assert events[-1]["data"]["ok"] is False
        assert client.get(f"/sessions/{session}").json()["provider_calls"] == 1
    assert not list(settings.sandbox_root.rglob("never.txt"))


def test_provider_exception_is_not_exposed_to_response_or_logs(demo_settings, caplog):
    from agentguard_demo.api import create_app
    from agentguard_demo.providers import FakeChatModel
    from fastapi.testclient import TestClient

    class FailingModel(FakeChatModel):
        def _generate(self, *args, **kwargs):
            raise RuntimeError("synthetic-private-credential")

    with TestClient(create_app(demo_settings, provider=FailingModel())) as client:
        session = create_session(client)
        events = chat(client, session, "hello")
    assert events[-2]["data"]["code"] == "provider_error"
    assert events[-1]["data"]["ok"] is False
    assert "synthetic-private-credential" not in json.dumps(events) + caplog.text


def test_second_session_has_distinct_note_directory(demo_client, demo_settings):
    first, second = create_session(demo_client), create_session(demo_client)
    for session, content in [(first, "A"), (second, "B")]:
        assert chat(
            demo_client, session, f'write_note {{"name":"same.txt","content":"{content}"}}'
        )[-1]["data"]["ok"]
    assert (demo_settings.sandbox_root / "notes" / first / "same.txt").read_text() == "A"
    assert (demo_settings.sandbox_root / "notes" / second / "same.txt").read_text() == "B"


def test_process_wide_call_limit_cannot_be_reset_by_creating_a_new_session(demo_settings):
    from agentguard_demo.api import create_app
    from fastapi.testclient import TestClient

    settings = demo_settings.model_copy(update={"max_total_provider_calls": 1})
    with TestClient(create_app(settings)) as client:
        first, second = create_session(client), create_session(client)
        assert chat(client, first, "one")[-1]["data"]["ok"] is True
        events = chat(client, second, "two")
        assert events[-2]["data"]["code"] == "total_provider_call_limit"
        assert client.get(f"/sessions/{second}").json()["provider_calls"] == 0


def test_event_iterator_yields_call_before_real_tool_execution(demo_client, demo_settings):
    service = demo_client.app.state.chat
    session = service.create_session()
    iterator = service.events(session, 'write_note {"name":"streamed.txt","content":"x"}')
    assert next(iterator)["event"] == "session"
    assert session.provider_calls == 0
    target = demo_settings.sandbox_root / "notes" / session.session_id / "streamed.txt"
    assert next(iterator)["event"] == "tool_call"
    assert not target.exists()
    assert next(iterator)["event"] == "tool_result"
    assert target.read_text() == "x"
    assert list(iterator)[-1]["data"]["ok"] is True
