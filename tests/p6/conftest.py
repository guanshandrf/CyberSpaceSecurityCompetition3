import pytest


@pytest.fixture
def adapter_case(tmp_path):
    # Lazy imports keep a pure SDK environment able to collect/deselect P6.
    from agentguard.adapters.langgraph import protect
    from agentguard.audit import SQLiteAudit
    from agentguard.contracts import SecurityContext
    from agentguard.policies import ToolBinding

    def make(
        *,
        handler=None,
        review=False,
        description="Echo a bounded string.",
        permissions=("fixture.use",),
        budget=8,
        detectors=(),
        gate2=None,
        admin_permissions=("tool.register", "fixture.use"),
        ttl=300,
        gate0=None,
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
            **claims, context_id="catalog.test", permissions=admin_permissions
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
        adapter = protect(
            [binding],
            descriptions={"echo": description},
            context=context,
            registration_context=admin,
            audit=audit,
            detectors=detectors,
            gate2=gate2,
            registration_ttl=ttl,
            gate0=gate0,
        )
        return adapter, calls, audit, claims

    return make


@pytest.fixture
def framework_call():
    return {"name": "echo", "args": {"text": "public fixture"}, "id": "call.1", "type": "tool_call"}


@pytest.fixture
def run_graph():
    from agentguard_demo.providers import FakeChatModel
    from langchain_core.messages import HumanMessage, ToolMessage
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langsmith import tracing_context
    from pydantic import Field

    class ObservedFake(FakeChatModel):
        received: list = Field(default_factory=list)

        def _generate(self, messages, *args, **kwargs):
            self.received.extend(m.content for m in messages if isinstance(m, ToolMessage))
            return super()._generate(messages, *args, **kwargs)

    def run(adapter, *, text='echo {"text":"public fixture"}', trace_id="trace.test"):
        provider = ObservedFake()
        bound = provider.bind_tools(adapter.tools(trace_id=trace_id))
        graph = StateGraph(MessagesState)
        graph.add_node("model", lambda state: {"messages": [bound.invoke(state["messages"])]})
        graph.add_node("tools", adapter.tool_node(trace_id=trace_id))
        graph.add_edge(START, "model")
        graph.add_conditional_edges(
            "model", lambda state: "tools" if state["messages"][-1].tool_calls else END
        )
        graph.add_edge("tools", "model")
        with tracing_context(enabled=False):
            result = graph.compile().invoke({"messages": [HumanMessage(content=text)]})
        return result["messages"], provider.received

    return run
