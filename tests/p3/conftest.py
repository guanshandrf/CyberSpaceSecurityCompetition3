from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentguard.audit import SQLiteAudit
from agentguard.contracts import SecurityContext, ToolCallEvent
from agentguard.executor import GuardedExecutor
from agentguard.policies import PathRule, ToolBinding


@pytest.fixture
def harness(tmp_path):
    root = tmp_path / "public"
    root.mkdir()
    (root / "sample.txt").write_text("public fixture", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("outside fixture", encoding="utf-8")
    count = []
    schema = {
        "type": "object",
        "properties": {"path": {"type": "string", "minLength": 1}},
        "required": ["path"],
        "additionalProperties": False,
    }

    def read_file(path):
        count.append(path)
        return Path(path).read_text(encoding="utf-8")

    def binding(**overrides):
        return ToolBinding(
            **{
                "tool_id": "reader",
                "name": "read_file",
                "handler": read_file,
                "parameters_schema": schema,
                "permissions": ("file.read",),
                "task_authorizations": ("task.read",),
                "paths": (PathRule("path", "resource.public", root),),
                **overrides,
            }
        )

    tool = binding()
    claims = {
        "schema_version": "1.0",
        "context_id": "context.1",
        "user_id": "user.1",
        "session_id": "session.1",
        "task_authorization": "task.read",
        "permissions": ["file.read"],
        "allowed_resources": ["resource.public"],
        "budget": {"max_calls": 2, "calls_used": 0},
    }

    def context(**overrides):
        return SecurityContext.from_backend(**{**claims, **overrides})

    def call(index=1, *, selected=None, **overrides):
        selected = tool if selected is None else selected
        return ToolCallEvent(
            **{
                "schema_version": "1.0",
                "event_type": "tool_call",
                "event_id": f"event.{index}",
                "tool_call_id": f"call.{index}",
                "timestamp": datetime(2026, 10, 20, tzinfo=UTC),
                "trace_id": "trace.1",
                "session_id": "session.1",
                "tool_id": selected.tool_id,
                "name": selected.name,
                "metadata_digest": selected.metadata_digest,
                "source": "fixture.backend",
                "context_ref": "context.1",
                "arguments": {"path": "sample.txt"},
                **overrides,
            }
        )

    audit = SQLiteAudit(tmp_path / "audit.sqlite3")

    def executor(*, tools=None, **options):
        return GuardedExecutor([tool] if tools is None else tools, audit=audit, **options)

    return SimpleNamespace(
        root=root,
        count=count,
        schema=schema,
        tool=tool,
        binding=binding,
        claims=claims,
        context=context,
        call=call,
        audit=audit,
        executor=executor,
    )
