import pytest

pytestmark = pytest.mark.p2


def test_registration_call_result_decisions_bind_to_their_own_gate_and_ids(
    registration_data,
    call_data,
    result_data,
    backend_context,
    decision_data,
):
    from agentguard.contracts import SecurityDecision, parse_event, validate_correlation

    call = parse_event(call_data)
    for data, gate in [(registration_data, "gate0"), (call_data, "gate1"), (result_data, "gate2")]:
        event = parse_event(data)
        decision = SecurityDecision(
            **{
                **decision_data,
                "gate": gate,
                "event_id": event.event_id,
                "tool_call_id": getattr(event, "tool_call_id", None),
            }
        )
        validate_correlation(
            event,
            context=backend_context,
            call=call if gate == "gate2" else None,
            decision=decision,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("tool_call_id", "other.call"),
        ("tool_id", "other.tool"),
        ("name", "other_name"),
        ("metadata_digest", "b" * 64),
        ("trace_id", "other.trace"),
        ("session_id", "other.session"),
        ("event_id", "event.call"),
    ],
)
def test_result_cannot_be_associated_with_different_call(
    call_data, result_data, backend_context, field, value
):
    from agentguard.contracts import CorrelationError, parse_event, validate_correlation

    result_data[field] = value
    with pytest.raises(CorrelationError):
        validate_correlation(
            parse_event(result_data), context=backend_context, call=parse_event(call_data)
        )


@pytest.mark.parametrize(
    "field,value", [("context_ref", "forged.context"), ("session_id", "other.session")]
)
def test_call_requires_matching_backend_context(call_data, backend_context, field, value):
    from agentguard.contracts import CorrelationError, parse_event, validate_correlation

    call_data[field] = value
    with pytest.raises(CorrelationError):
        validate_correlation(parse_event(call_data), context=backend_context)


@pytest.mark.parametrize(
    "field,value",
    [
        ("event_id", "wrong.event"),
        ("tool_call_id", "wrong.call"),
        ("trace_id", "wrong.trace"),
        ("session_id", "wrong.session"),
        ("tool_id", "wrong.tool"),
        ("gate", "gate2"),
    ],
)
def test_decision_cannot_be_reused_for_different_event(
    call_data, decision_data, backend_context, field, value
):
    from agentguard.contracts import (
        CorrelationError,
        SecurityDecision,
        parse_event,
        validate_correlation,
    )

    decision_data[field] = value
    with pytest.raises(CorrelationError):
        validate_correlation(
            parse_event(call_data),
            context=backend_context,
            decision=SecurityDecision(**decision_data),
        )


def test_results_require_call_and_raw_json_context_is_not_trusted(
    result_data, call_data, context_data, backend_context
):
    from agentguard.contracts import CorrelationError, parse_event, validate_correlation

    with pytest.raises(CorrelationError, match="originating"):
        validate_correlation(parse_event(result_data), context=backend_context)
    with pytest.raises(CorrelationError, match="backend"):
        validate_correlation(parse_event(call_data), context=context_data)
    with pytest.raises(CorrelationError, match="only applicable"):
        validate_correlation(
            parse_event(call_data), context=backend_context, call=parse_event(call_data)
        )


def test_mutated_decision_replacement_is_revalidated(
    result_data, call_data, backend_context, decision_data
):
    from pydantic import ValidationError

    from agentguard.contracts import SecurityDecision, parse_event, validate_correlation

    decision_data.update(
        gate="gate2",
        event_id="event.result",
        action="SANITIZE",
        replacement_content={"text": "synthetic replacement"},
    )
    decision = SecurityDecision(**decision_data)
    decision.replacement_content["bad"] = float("nan")
    with pytest.raises(ValidationError):
        validate_correlation(
            parse_event(result_data),
            context=backend_context,
            call=parse_event(call_data),
            decision=decision,
        )
