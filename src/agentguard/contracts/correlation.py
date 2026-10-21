"""Pure correlation checks; no permissions, policy or tool execution decisions."""

from .models import (
    SecurityContext,
    SecurityDecision,
    ToolCallEvent,
    ToolRegistrationEvent,
    ToolResultEvent,
    UnifiedEvent,
    parse_event,
)


class CorrelationError(ValueError):
    pass


def validate_correlation(
    event: UnifiedEvent,
    *,
    context: SecurityContext,
    call: ToolCallEvent | None = None,
    decision: SecurityDecision | None = None,
) -> None:
    event = parse_event(event)
    if type(context) is not SecurityContext or not context.has_backend_provenance():
        raise CorrelationError("A backend-constructed context is required")
    if event.session_id != context.session_id:
        raise CorrelationError("Event/context session mismatch")
    if isinstance(event, ToolCallEvent) and event.context_ref != context.context_id:
        raise CorrelationError("Call/context reference mismatch")
    if isinstance(event, ToolResultEvent):
        if not isinstance(call, ToolCallEvent):
            raise CorrelationError("A result requires its originating call")
        call = parse_event(call)
        validate_correlation(call, context=context)
        if event.event_id == call.event_id:
            raise CorrelationError("Call and result must have distinct event IDs")
        fields = ("tool_call_id", "tool_id", "name", "metadata_digest", "trace_id", "session_id")
        if any(getattr(event, name) != getattr(call, name) for name in fields):
            raise CorrelationError("Call/result association mismatch")
    elif call is not None:
        raise CorrelationError("Originating call is only applicable to result events")
    if decision is not None:
        decision = SecurityDecision.model_validate(
            {
                name: getattr(decision, name)
                for name in type(decision).model_fields
                if hasattr(decision, name)
            }
        )
        gate = (
            "gate0"
            if isinstance(event, ToolRegistrationEvent)
            else "gate1"
            if isinstance(event, ToolCallEvent)
            else "gate2"
        )
        fields = ("event_id", "trace_id", "session_id", "tool_id")
        if decision.gate != gate or any(
            getattr(event, name) != getattr(decision, name) for name in fields
        ):
            raise CorrelationError("Event/decision association mismatch")
        if getattr(event, "tool_call_id", None) != decision.tool_call_id:
            raise CorrelationError("Decision tool_call_id mismatch")
