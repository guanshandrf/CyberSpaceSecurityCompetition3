import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

pytestmark = pytest.mark.p2


@pytest.mark.parametrize(
    "fixture_name,expected",
    [
        ("registration_data", "tool_registration"),
        ("call_data", "tool_call"),
        ("result_data", "tool_result"),
    ],
)
def test_three_event_types_roundtrip_as_python_dict_json_and_bytes(request, fixture_name, expected):
    from agentguard.contracts import parse_event

    event = parse_event(request.getfixturevalue(fixture_name))
    assert event.event_type == expected
    assert parse_event(event.model_dump_json()) == event
    assert parse_event(event.model_dump_json().encode()) == event
    assert parse_event(event.model_dump(mode="json")) == event
    assert parse_event(event) == event


@pytest.mark.parametrize(
    "missing",
    [
        "schema_version",
        "event_id",
        "event_type",
        "timestamp",
        "trace_id",
        "session_id",
        "tool_id",
        "name",
        "metadata_digest",
        "tool_call_id",
        "arguments",
        "context_ref",
        "source",
    ],
)
def test_call_required_fields_are_not_silently_defaulted(call_data, missing):
    from agentguard.contracts import parse_event

    del call_data[missing]
    with pytest.raises(ValidationError):
        parse_event(call_data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "2.0"),
        ("event_type", "system"),
        ("event_id", ""),
        ("event_id", "contains space"),
        ("tool_call_id", 123),
        ("metadata_digest", "not-a-digest"),
        ("arguments", []),
        ("source", ""),
        ("source", " "),
        ("unknown", True),
        ("user_id", "admin"),
    ],
)
def test_invalid_version_type_ids_and_extra_fields_rejected(call_data, field, value):
    from agentguard.contracts import parse_event

    call_data[field] = value
    with pytest.raises(ValidationError):
        parse_event(call_data)


def test_timestamp_requires_timezone_and_normalizes_utc(call_data):
    from agentguard.contracts import parse_event

    call_data["timestamp"] = datetime(2026, 10, 20, 8, tzinfo=timezone(timedelta(hours=8)))
    assert parse_event(call_data).timestamp == datetime(2026, 10, 20, tzinfo=UTC)
    call_data["timestamp"] = datetime(2026, 10, 20)
    with pytest.raises(ValidationError):
        parse_event(call_data)


@pytest.mark.parametrize(
    "payload",
    [
        {"x": b"bytes"},
        {"x": {1, 2}},
        {1: "non-string-key"},
        {"x": (1, 2)},
        {"x": float("nan")},
        {"x": float("inf")},
        {"x": datetime(2026, 10, 20, tzinfo=UTC)},
        {"x": "a" * (16 * 1024)},
    ],
)
def test_arguments_are_finite_bounded_native_json(call_data, payload):
    from agentguard.contracts import parse_event

    call_data["arguments"] = payload
    with pytest.raises(ValidationError):
        parse_event(call_data)


def test_deep_and_cyclic_payloads_fail_without_recursion_crash(call_data):
    from agentguard.contracts import parse_event

    deep = root = {}
    for _ in range(20):
        deep["next"] = {}
        deep = deep["next"]
    for payload in (root, {"self": None}):
        if "self" in payload:
            payload["self"] = payload
        call_data["arguments"] = payload
        with pytest.raises(ValidationError):
            parse_event(call_data)


def test_input_snapshots_are_detached_and_sensitive_payloads_not_in_repr(call_data):
    from agentguard.contracts import parse_event

    call_data["arguments"] = {"secret": ["synthetic-private-value"]}
    event = parse_event(call_data)
    call_data["arguments"]["secret"].append("caller-mutated")
    assert event.arguments == {"secret": ["synthetic-private-value"]}
    assert "synthetic-private-value" not in repr(event)


@pytest.mark.parametrize("schema", [{}, {"type": "array"}, {"type": "object", "properties": []}])
def test_registration_requires_object_schema(registration_data, schema):
    from agentguard.contracts import parse_event

    registration_data["parameters_schema"] = schema
    with pytest.raises(ValidationError):
        parse_event(registration_data)


@pytest.mark.parametrize(
    "changes",
    [
        {"result_type": "text", "content": {}},
        {"is_error": True},
        {"result_type": "error"},
        {"is_error": "false"},
        {"content": "a" * (64 * 1024)},
        {"truncated": True},
        {"truncated": True, "original_size": 2, "evidence_ref": "evidence.1"},
        {"original_size": 999},
    ],
)
def test_result_shape_and_truncation_metadata_are_validated(result_data, changes):
    from agentguard.contracts import parse_event

    result_data.update(changes)
    with pytest.raises(ValidationError):
        parse_event(result_data)


def test_explicit_error_and_truncated_results_roundtrip(result_data):
    from agentguard.contracts import parse_event

    result_data.update(result_type="error", is_error=True, content={"code": "fixture.error"})
    error = parse_event(result_data)
    assert parse_event(error.model_dump_json()) == error
    result_data.update(
        result_type="text",
        is_error=False,
        content="short",
        truncated=True,
        original_size=100,
        evidence_ref="evidence.original",
    )
    assert parse_event(result_data).original_size == 100


def test_wire_size_and_abstract_envelope_are_rejected(event_common):
    from agentguard.contracts import SecurityEvent, parse_event

    with pytest.raises(ValueError, match="256 KiB"):
        parse_event(" " * (256 * 1024 + 1))
    envelope = {
        key: event_common[key]
        for key in (
            "schema_version",
            "event_id",
            "event_type",
            "timestamp",
            "trace_id",
            "session_id",
        )
    }
    with pytest.raises(ValidationError, match="concrete"):
        SecurityEvent(**envelope)
    with pytest.raises(ValidationError):
        parse_event(json.dumps({"event_type": "tool_call"}))


@pytest.mark.parametrize("value", [b"not-text", float("nan"), {"not-json"}])
def test_mutated_payload_is_revalidated_before_lossy_json_serialization(call_data, value):
    from agentguard.contracts import parse_event

    event = parse_event(call_data)
    event.arguments["invalid"] = value
    with pytest.raises(ValidationError):
        parse_event(event)


def test_unchecked_event_model_copy_must_be_revalidated(call_data):
    from agentguard.contracts import parse_event

    event = parse_event(call_data).model_copy(update={"tool_call_id": ""})
    with pytest.raises(ValidationError):
        parse_event(event)
