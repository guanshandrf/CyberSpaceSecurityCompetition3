import pytest


@pytest.fixture
def simple_case(tmp_path):
    from agentguard.adapters.simple import SimpleAdapter
    from agentguard.audit import SQLiteAudit
    from agentguard.contracts import SecurityContext
    from agentguard.policies import ToolBinding

    def make(
        *,
        review=False,
        handler=None,
        permissions=("fixture.use",),
        budget=20,
        ttl=300,
        approval_ttl=300,
        detectors=(),
        gate0=None,
        gate2=None,
        capacity=16,
    ):
        calls = []

        def execute(text):
            calls.append(text)
            return handler(text) if handler else {"echo": text}

        claims = dict(
            schema_version="1.0",
            user_id="backend.user",
            session_id="session.test",
            task_authorization="task.test",
            allowed_resources=(),
            budget={"max_calls": budget, "calls_used": 0},
        )
        context = SecurityContext.from_backend(
            **claims, context_id="context.test", permissions=permissions
        )
        admin = SecurityContext.from_backend(
            **claims,
            context_id="catalog.test",
            permissions=("tool.register", "fixture.use", "guard.approve"),
        )
        binding = ToolBinding(
            tool_id="fixture.echo",
            name="echo",
            handler=execute,
            parameters_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            },
            permissions=("fixture.use",),
            task_authorizations=("task.test",),
            requires_review=review,
        )
        audit = SQLiteAudit(tmp_path / f"audit-{len(list(tmp_path.glob('audit-*')))}.sqlite")
        adapter = SimpleAdapter(
            [binding],
            descriptions={"echo": "Echo a bounded string."},
            context=context,
            registration_context=admin,
            audit=audit,
            registration_ttl=ttl,
            approval_ttl=approval_ttl,
            max_pending_approvals=capacity,
            detectors=detectors,
            gate0=gate0,
            gate2=gate2,
        )
        return adapter, calls, audit, claims, admin

    return make


@pytest.fixture
def request_call():
    return {"name": "echo", "arguments": {"text": "public fixture"}, "tool_call_id": "call.1"}
