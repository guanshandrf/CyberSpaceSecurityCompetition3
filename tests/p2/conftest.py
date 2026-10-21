from datetime import UTC, datetime

import pytest


@pytest.fixture
def event_common():
    return {
        "schema_version": "1.0",
        "event_id": "event.call",
        "event_type": "tool_call",
        "timestamp": datetime(2026, 10, 20, tzinfo=UTC),
        "trace_id": "trace.1",
        "session_id": "session.1",
        "tool_id": "reader",
        "name": "read_file",
        "metadata_digest": "a" * 64,
        "source": "fixture.backend",
    }


@pytest.fixture
def call_data(event_common):
    return {
        **event_common,
        "tool_call_id": "invocation.1",
        "arguments": {"path": "sample.txt"},
        "context_ref": "context.1",
    }


@pytest.fixture
def registration_data(event_common):
    return {
        **event_common,
        "event_id": "event.registration",
        "event_type": "tool_registration",
        "description": "Read a public fixture",
        "parameters_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
        },
        "capabilities": ["read"],
        "permissions": ["fixture.read"],
    }


@pytest.fixture
def result_data(event_common):
    return {
        **event_common,
        "event_id": "event.result",
        "event_type": "tool_result",
        "tool_call_id": "invocation.1",
        "result_type": "text",
        "content": "public result",
        "is_error": False,
    }


@pytest.fixture
def context_data():
    return {
        "schema_version": "1.0",
        "context_id": "context.1",
        "user_id": "backend.user",
        "session_id": "session.1",
        "task_authorization": "task.read",
        "allowed_resources": ["fixture.sample"],
        "permissions": ["fixture.read"],
        "budget": {"max_calls": 2, "calls_used": 0},
    }


@pytest.fixture
def backend_context(context_data):
    from agentguard.contracts import SecurityContext

    return SecurityContext.from_backend(**context_data)


@pytest.fixture
def decision_data():
    return {
        "schema_version": "1.0",
        "gate": "gate1",
        "event_id": "event.call",
        "trace_id": "trace.1",
        "session_id": "session.1",
        "tool_id": "reader",
        "tool_call_id": "invocation.1",
        "action": "BLOCK",
        "reason_codes": ["fixture.deny"],
    }
