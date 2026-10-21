"""Synthetic P2 event normalization only: no framework, model, tool execution or Guard."""

import hashlib
import json
from datetime import UTC, datetime

from agentguard.contracts import (
    SecurityContext,
    ToolCallEvent,
    ToolRegistrationEvent,
    ToolResultEvent,
    parse_event,
    validate_correlation,
)


class MockAdapter:
    def events(self):
        schema = {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        }
        digest = hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()
        common = {
            "schema_version": "1.0",
            "timestamp": datetime.now(UTC),
            "trace_id": "fixture.trace",
            "session_id": "fixture.session",
            "tool_id": "fixture.reader",
            "name": "read_sample",
            "metadata_digest": digest,
            "source": "synthetic-adapter",
        }
        registered = ToolRegistrationEvent(
            **common,
            event_id="registration.1",
            event_type="tool_registration",
            description="Read fixture",
            parameters_schema=schema,
            capabilities=["read"],
            permissions=["fixture.read"],
        )
        called = ToolCallEvent(
            **common,
            event_id="call.1",
            event_type="tool_call",
            tool_call_id="invocation.1",
            context_ref="context.1",
            arguments={"path": "sample.txt"},
        )
        result = ToolResultEvent(
            **common,
            event_id="result.1",
            event_type="tool_result",
            tool_call_id="invocation.1",
            result_type="text",
            content="public synthetic content",
            is_error=False,
        )
        return registered, called, result


def main():
    context = SecurityContext.from_backend(
        schema_version="1.0",
        context_id="context.1",
        user_id="fixture.user",
        session_id="fixture.session",
        task_authorization="fixture.task",
        allowed_resources=["fixture.sample"],
        permissions=["fixture.read"],
        budget={"max_calls": 1, "calls_used": 0},
    )
    registration, call, result = MockAdapter().events()
    validate_correlation(registration, context=context)
    validate_correlation(call, context=context)
    validate_correlation(result, context=context, call=call)
    events = [
        parse_event(event.model_dump_json()).model_dump(mode="json")
        for event in (registration, call, result)
    ]
    print(
        json.dumps(
            {"synthetic": True, "tool_executions": 0, "guard_enforced": False, "events": events},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
