from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from agentguard.audit import SQLiteAudit
from agentguard.contracts import SecurityContext, ToolCallEvent, ToolResultEvent
from agentguard.executor import ResultHandler


@pytest.fixture
def result_case(tmp_path):
    context = SecurityContext.from_backend(
        schema_version="1.0",
        context_id="ctx.1",
        user_id="user.1",
        session_id="s.1",
        task_authorization="task.read",
        permissions=["file.read"],
        allowed_resources=["public"],
        budget={"max_calls": 4, "calls_used": 0},
    )
    call = ToolCallEvent(
        schema_version="1.0",
        event_type="tool_call",
        event_id="call.event",
        tool_call_id="call.1",
        timestamp=datetime.now(UTC),
        trace_id="trace.1",
        session_id="s.1",
        tool_id="reader",
        name="read_file",
        metadata_digest="a" * 64,
        arguments={},
        source="test.backend",
        context_ref="ctx.1",
    )

    def result(content="public fixture", **overrides):
        return ToolResultEvent(
            **{
                **{
                    key: getattr(call, key)
                    for key in (
                        "schema_version",
                        "timestamp",
                        "trace_id",
                        "session_id",
                        "tool_id",
                        "name",
                        "metadata_digest",
                        "tool_call_id",
                    )
                },
                "event_id": "result.event",
                "event_type": "tool_result",
                "source": "fixture.untrusted",
                "result_type": "text" if type(content) is str else "json",
                "is_error": False,
                "content": content,
                **overrides,
            }
        )

    audit = SQLiteAudit(tmp_path / "audit.sqlite3")
    handler = ResultHandler(audit=audit)
    return SimpleNamespace(context=context, call=call, result=result, audit=audit, handler=handler)
