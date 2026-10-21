from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from agentguard.audit import SQLiteAudit
from agentguard.contracts import SecurityContext, ToolCallEvent
from agentguard.executor import GuardedExecutor
from agentguard.policies import ToolBinding
from agentguard.registry import ToolRegistry


@pytest.fixture
def registration_case(tmp_path):
    path = tmp_path / "public.txt"
    path.write_text("public registered fixture", encoding="utf-8")
    executions = []

    def read():
        executions.append(1)
        return path.read_text(encoding="utf-8")

    binding = ToolBinding(
        tool_id="reader",
        name="read_file",
        handler=read,
        parameters_schema={"type": "object", "properties": {}, "additionalProperties": False},
        permissions=("file.read",),
        task_authorizations=("task.read",),
        resources=("public",),
    )
    claims = dict(
        schema_version="1.0",
        context_id="ctx.1",
        session_id="s.1",
        user_id="user.1",
        task_authorization="task.read",
        permissions=["file.read"],
        allowed_resources=["public"],
        budget={"max_calls": 4, "calls_used": 0},
    )
    context = SecurityContext.from_backend(**claims)
    admin = SecurityContext.from_backend(
        **{
            **claims,
            "context_id": "ctx.admin",
            "permissions": ["file.read", "tool.register", "tool.approve"],
        }
    )
    audit = SQLiteAudit(tmp_path / "audit.sqlite3")
    registry = ToolRegistry(audit=audit)

    def register(**kwargs):
        return registry.register(
            binding, admin, **{"description": "Read a public fixture", **kwargs}
        )

    def call(registration, index=1):
        return ToolCallEvent(
            schema_version="1.0",
            event_type="tool_call",
            event_id=f"event.{index}",
            timestamp=datetime.now(UTC),
            trace_id="trace.1",
            session_id="s.1",
            tool_id="reader",
            name="read_file",
            metadata_digest=registration.event.metadata_digest,
            tool_call_id=f"call.{index}",
            arguments={},
            source="test.adapter",
            context_ref="ctx.1",
        )

    def executor(**kwargs):
        return GuardedExecutor([], registry=registry, audit=audit, **kwargs)

    return SimpleNamespace(
        binding=binding,
        context=context,
        admin=admin,
        claims=claims,
        audit=audit,
        registry=registry,
        register=register,
        call=call,
        executor=executor,
        executions=executions,
    )
