"""Backend raw evidence stays separate; only safe_event belongs in an Agent message."""

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from agentguard.contracts import (
    SecurityDecision,
    ToolResultEvent,
    parse_event,
    validate_correlation,
)
from agentguard.gates import Gate2
from agentguard.gates.gate1 import call_snapshot, trusted_snapshot
from agentguard.gates.gate2 import result_decision


@dataclass(frozen=True)
class HandledResult:
    decision: SecurityDecision = field(repr=False)
    safe_event: ToolResultEvent = field(repr=False)
    raw_event: ToolResultEvent | None = field(default=None, repr=False)


def _result_for(call, content, *, error=False):
    return ToolResultEvent(
        schema_version="1.0",
        event_type="tool_result",
        event_id="result." + uuid.uuid4().hex,
        timestamp=datetime.now(UTC),
        trace_id=call.trace_id,
        session_id=call.session_id,
        tool_id=call.tool_id,
        name=call.name,
        metadata_digest=call.metadata_digest,
        tool_call_id=call.tool_call_id,
        source="agentguard.executor",
        result_type="error" if error else "text" if type(content) is str else "json",
        content=content,
        is_error=error,
    )


def _safe_event(event, content, *, blocked=False):
    data = {name: getattr(event, name) for name in ToolResultEvent.model_fields}
    data.update(
        content=content,
        source="agentguard.gate2",
        truncated=False,
        original_size=None,
        evidence_ref=None,
    )
    if blocked:
        data.update(result_type="error", is_error=True)
    elif not event.is_error:
        data["result_type"] = "text" if type(content) is str else "json"
    return ToolResultEvent(**data)


class ResultHandler:
    def __init__(self, *, audit, gate=None):
        self._audit = audit
        self._gate = Gate2() if gate is None else gate

    def after_tool(self, event, context, *, call):
        started = time.monotonic()
        try:
            call = call_snapshot(call)
            context = trusted_snapshot(context)
            validate_correlation(call, context=context)
        except Exception:
            raise ValueError("Trusted originating call required") from None
        raw = None
        try:
            candidate = parse_event(event)
            if type(candidate) is not ToolResultEvent:
                raise ValueError
            validate_correlation(candidate, context=context, call=call)
            raw = candidate
            decision = self._gate.after_tool(parse_event(raw), context, call=call_snapshot(call))
            if type(decision) is not SecurityDecision:
                raise ValueError
            decision = SecurityDecision.model_validate(
                {name: getattr(decision, name) for name in SecurityDecision.model_fields}
            )
            validate_correlation(raw, context=context, call=call, decision=decision)
        except Exception:
            candidate = (
                raw
                if raw is not None
                else _result_for(call, {"error": "result.invalid"}, error=True)
            )
            decision = result_decision(candidate, "BLOCK", "result.invalid")
        try:
            if decision.action == "BLOCK":
                safe = _safe_event(candidate, {"error": "guard.result_blocked"}, blocked=True)
            elif decision.action == "SANITIZE":
                safe = _safe_event(candidate, decision.replacement_content)
            elif decision.action == "ALLOW":
                safe = _safe_event(candidate, parse_event(candidate).content)
            else:
                raise ValueError
        except Exception:
            decision = result_decision(candidate, "BLOCK", "check.failed")
            safe = _safe_event(candidate, {"error": "guard.result_blocked"}, blocked=True)
        try:
            self._audit.append(
                decision, stage="handled", duration_ms=(time.monotonic() - started) * 1000
            )
        except Exception:
            decision = result_decision(candidate, "BLOCK", "audit.failed")
            safe = _safe_event(candidate, {"error": "guard.result_blocked"}, blocked=True)
        return HandledResult(decision, safe, raw)

    def handle_execution(self, execution, context, *, call):
        from .guarded import ExecutionResult

        call = call_snapshot(call)
        if type(execution) is not ExecutionResult:
            raise ValueError("Executor result required")
        try:
            content = execution.value
            error = execution.error_code is not None or not execution.executed
            if error:
                content = {"error": "tool.failed" if execution.executed else "tool.not_executed"}
            event = _result_for(call, content, error=error)
        except Exception:
            event = None
        return self.after_tool(event, context, call=call)
