import json

import pytest
from pydantic import ValidationError

pytestmark = pytest.mark.p2


def test_context_only_roundtrips_through_explicit_backend_entry(context_data):
    from agentguard.contracts import SecurityContext

    context = SecurityContext.from_backend(**context_data)
    assert context.has_backend_provenance()
    restored = SecurityContext.from_backend(**json.loads(context.model_dump_json()))
    assert restored == context
    assert context.permissions == ("fixture.read",)
    assert "backend.user" not in repr(context)


@pytest.mark.parametrize("method", ["constructor", "dict", "json", "fake-validation-context"])
def test_llm_json_and_claimed_trust_cannot_construct_context(context_data, method):
    from agentguard.contracts import SecurityContext

    with pytest.raises(ValidationError, match="trusted backend"):
        if method == "constructor":
            SecurityContext(**context_data)
        elif method == "dict":
            SecurityContext.model_validate(context_data)
        elif method == "json":
            SecurityContext.model_validate_json(json.dumps(context_data))
        else:
            SecurityContext.model_validate(context_data, context={"backend": True, "trusted": True})


@pytest.mark.parametrize(
    "field,value",
    [
        ("trusted", True),
        ("origin", "backend"),
        ("_backend_origin", "backend"),
        ("api_key", "synthetic-private-value"),
        ("schema_version", "2.0"),
        ("permissions", "admin"),
        ("budget", {"max_calls": 0, "calls_used": 0}),
        ("budget", {"max_calls": 2, "calls_used": -1}),
    ],
)
def test_backend_entry_still_rejects_extra_and_invalid_claims(context_data, field, value):
    from agentguard.contracts import SecurityContext

    context_data[field] = value
    with pytest.raises(ValidationError):
        SecurityContext.from_backend(**context_data)


def test_context_identity_permissions_and_budget_are_immutable(backend_context, context_data):
    from agentguard.contracts import SecurityContext

    with pytest.raises(ValidationError):
        backend_context.user_id = "admin"
    with pytest.raises(ValidationError):
        backend_context.budget.max_calls = 999
    with pytest.raises(TypeError):
        backend_context.model_copy(update={"permissions": ("admin",)})
    context_data["permissions"].append("admin")
    assert backend_context.permissions == ("fixture.read",)
    for copy in [backend_context.model_copy(), backend_context.model_copy(deep=True)]:
        assert copy.has_backend_provenance()
        assert copy.permissions == backend_context.permissions
    rebuilt = SecurityContext.from_backend(**context_data)
    assert rebuilt.permissions == ("fixture.read", "admin")  # Only explicit trusted backend input.


def test_model_construct_without_validation_cannot_acquire_backend_provenance(
    context_data, call_data
):
    from agentguard.contracts import (
        CorrelationError,
        SecurityContext,
        parse_event,
        validate_correlation,
    )

    unchecked = SecurityContext.model_construct(**context_data)
    assert not unchecked.has_backend_provenance()
    with pytest.raises(CorrelationError, match="backend"):
        validate_correlation(parse_event(call_data), context=unchecked)


def test_model_claims_in_tool_arguments_do_not_modify_trusted_identity(call_data, backend_context):
    from agentguard.contracts import parse_event, validate_correlation

    call_data["arguments"].update(user_id="admin", permissions=["root"], trusted=True)
    call = parse_event(call_data)
    assert validate_correlation(call, context=backend_context) is None
    assert backend_context.user_id == "backend.user"
    assert backend_context.permissions == ("fixture.read",)
    # Correlation is not permission evaluation; the argument text grants no rights.


def test_validation_error_string_hides_raw_sensitive_input(call_data):
    from agentguard.contracts import parse_event

    call_data["arguments"] = {"secret": b"synthetic-private-value"}
    with pytest.raises(ValidationError) as caught:
        parse_event(call_data)
    assert "synthetic-private-value" not in str(caught.value)
