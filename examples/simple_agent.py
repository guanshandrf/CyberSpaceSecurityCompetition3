"""A bounded, offline Python agent loop. No graph, provider or web dependency."""

import json
from pathlib import Path

from agentguard.adapters.simple import SimpleAdapter
from agentguard.audit import SQLiteAudit
from agentguard.contracts import SecurityContext
from agentguard.policies import ToolBinding


def build_adapter(directory, *, budget=4):
    calls = []

    def echo(text):
        calls.append(text)
        return {"echo": text}

    claims = dict(
        schema_version="1.0",
        user_id="local.user",
        session_id="simple.session",
        task_authorization="task.echo",
        allowed_resources=(),
        budget={"max_calls": budget, "calls_used": 0},
    )
    context = SecurityContext.from_backend(
        **claims, context_id="simple.context", permissions=("echo.use",)
    )
    catalog = SecurityContext.from_backend(
        **claims, context_id="simple.catalog", permissions=("tool.register", "echo.use")
    )
    binding = ToolBinding(
        tool_id="local.echo",
        name="echo",
        handler=echo,
        parameters_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
        permissions=("echo.use",),
        task_authorizations=("task.echo",),
    )
    audit = SQLiteAudit(directory / "audit.sqlite")
    return SimpleAdapter(
        [binding],
        descriptions={"echo": "Echo a bounded string."},
        context=context,
        registration_context=catalog,
        audit=audit,
    ), calls


def run_loop(adapter):
    # Deterministic local model substitute. Actual SDK, tools and audit execute.
    history = []
    for _ in range(3):
        if not history:
            request = {
                "name": "echo",
                "arguments": {"text": "Hello AgentGuard"},
                "tool_call_id": "simple.call.1",
            }
            reply = adapter.invoke(request, trace_id="simple.trace.1")
            history.append(reply.safe_event.content)
        else:
            return {"answer": history[-1]["echo"], "source": "offline deterministic agent"}
    raise RuntimeError("Loop limit reached")


def main():
    # Require invocation from repository root; never search upward or read .env.
    root = Path.cwd()
    if not (root / "AGENTS.md").is_file():
        raise SystemExit("Run from the AgentGuard repository root")
    directory = root / ".cache" / "simple-demo"
    directory.mkdir(parents=True, exist_ok=True)
    adapter, calls = build_adapter(directory)
    result = run_loop(adapter)
    assert len(calls) == 1
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
