"""Benchmark-owned bindings reuse the SDK without copying detection/policy rules."""

import json
from datetime import UTC, datetime
from uuid import uuid4

from agentguard.contracts import SecurityContext, ToolCallEvent
from agentguard.executor import GuardedExecutor, ResultHandler
from agentguard.policies import ToolBinding
from agentguard.registry import ToolRegistry


class MemoryAudit:
    def __init__(self):
        self.actions = []

    def append(self, decision, *, stage, duration_ms):
        self.actions.append(
            {
                "gate": decision.gate,
                "action": decision.action.value,
                "reason_codes": list(decision.reason_codes),
                "stage": stage,
                "duration_ms": duration_ms,
            }
        )


class GuardBridge:
    """Only backend-selected, in-memory/sandbox handlers may enter this experiment."""

    def __init__(self, tools, *, permissions=("bench.user",), mode="full"):
        if mode not in {"full", "rules", "without_gate0", "without_gate1", "without_gate2"}:
            raise ValueError("Unsupported protected mode")
        self.mode = mode
        session = "bench." + uuid4().hex
        self.context = SecurityContext.from_backend(
            schema_version="1.0",
            context_id="ctx." + session,
            user_id="offline.benchmark",
            session_id=session,
            task_authorization="task.benchmark",
            allowed_resources=(),
            permissions=permissions,
            budget={"max_calls": 16, "calls_used": 0},
        )
        self.audit = MemoryAudit()
        self.counts = {t["name"]: 0 for t in tools}
        self.handlers = {}
        bindings = []
        for tool in tools:
            name = tool["name"]

            def observed(_name=name, _handler=tool["handler"], **kwargs):
                self.counts[_name] += 1
                return _handler(**kwargs)

            self.handlers[name] = observed
            bindings.append(
                ToolBinding(
                    tool_id="bench." + name,
                    name=name,
                    handler=observed,
                    parameters_schema=tool["schema"],
                    permissions=(tool.get("permission", "bench.user"),),
                    task_authorizations=("task.benchmark",),
                )
            )
        admin = SecurityContext.from_backend(
            schema_version="1.0",
            context_id="admin." + session,
            user_id="benchmark.catalog",
            session_id=session,
            task_authorization="task.benchmark",
            allowed_resources=(),
            permissions=("tool.register", "bench.user", "bench.attack"),
            budget={"max_calls": 16, "calls_used": 0},
        )
        registry = ToolRegistry(audit=self.audit)
        self.bindings = {binding.name: binding for binding in bindings}
        self.registrations = {}
        for binding in bindings:
            result = registry.register(
                binding, admin, description="Bounded in-memory benchmark tool"
            )
            if result.decision.action != "ALLOW":
                raise ValueError("Benchmark binding failed Gate0 admission")
            self.registrations[binding.name] = result
        self.executor = GuardedExecutor(
            bindings if mode == "without_gate0" else [],
            audit=self.audit,
            registry=None if mode == "without_gate0" else registry,
        )
        self.results = ResultHandler(audit=self.audit)

    def call_event(self, name, arguments, *, call_id=None, trace_id=None):
        # Registry owns digests; use its public approved entry for the selected tool.
        binding = self.bindings[name]
        return ToolCallEvent(
            schema_version="1.0",
            event_type="tool_call",
            event_id="event." + uuid4().hex,
            timestamp=datetime.now(UTC),
            trace_id=trace_id or "trace." + uuid4().hex,
            session_id=self.context.session_id,
            tool_id=binding.tool_id,
            name=name,
            metadata_digest=(
                binding.metadata_digest
                if self.mode == "without_gate0"
                else self.registrations[name].event.metadata_digest
            ),
            tool_call_id=call_id or "call." + uuid4().hex,
            arguments=arguments,
            source="benchmark.adapter",
            context_ref=self.context.context_id,
        )

    def invoke(self, name, arguments, *, call_id=None, trace_id=None):
        call = self.call_event(name, arguments, call_id=call_id, trace_id=trace_id)
        if self.mode == "without_gate1":
            from agentguard.executor import ExecutionResult

            execution = ExecutionResult(None, executed=True, value=self.handlers[name](**arguments))
        else:
            execution = self.executor.execute(call, self.context)
        if self.mode == "without_gate2":
            return execution.value if execution.executed else {"error": "tool.not_executed"}
        return self.results.handle_execution(execution, self.context, call=call).safe_event.content

    def review_content(self, name, arguments, content):
        from agentguard.executor import ExecutionResult

        call = self.call_event(name, arguments)
        # An upstream benchmark preloads an observation; it is not a real tool execution.
        return self.results.handle_execution(
            ExecutionResult(None, executed=True, value=content), self.context, call=call
        ).safe_event.content


def scalar_schema(parameters, *, required=None):
    """Explicit supported JSON schema; never silently drop unknown constraints."""
    if any(t not in {"string", "number", "integer", "boolean"} for t in parameters.values()):
        raise ValueError("Unsupported benchmark parameter type")
    return {
        "type": "object",
        "properties": {k: {"type": v} for k, v in parameters.items()},
        "required": list(parameters) if required is None else required,
        "additionalProperties": False,
    }


def as_json(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [as_json(v) for v in value]
    return json.loads(json.dumps(value, allow_nan=False))
