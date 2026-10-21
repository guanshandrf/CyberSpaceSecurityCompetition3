import pytest
from pydantic import ValidationError

pytestmark = pytest.mark.p2


@pytest.mark.parametrize("action", ["ALLOW", "BLOCK", "REVIEW"])
def test_gate1_actions_roundtrip_without_any_execution(decision_data, action):
    from agentguard.contracts import SecurityDecision

    decision_data["action"] = action
    decision = SecurityDecision(**decision_data)
    assert SecurityDecision.model_validate_json(decision.model_dump_json()) == decision
    assert decision.action.value == action


@pytest.mark.parametrize(
    "missing",
    [
        "schema_version",
        "gate",
        "event_id",
        "trace_id",
        "session_id",
        "tool_id",
        "tool_call_id",
        "action",
        "reason_codes",
    ],
)
def test_decision_required_fields_have_no_implicit_allow(decision_data, missing):
    from agentguard.contracts import SecurityDecision

    del decision_data[missing]
    with pytest.raises(ValidationError):
        SecurityDecision(**decision_data)


@pytest.mark.parametrize(
    "changes",
    [
        {"action": "EXECUTE"},
        {"action": "allow"},
        {"action": True},
        {"schema_version": "0.9"},
        {"reason_codes": []},
        {"gate": "gate3"},
        {"trusted": True},
        {"risk_score": 0.0},
        {"action": "SANITIZE"},
        {"replacement_content": "must-not-be-used-with-BLOCK"},
        {"gate": "gate2", "action": "REVIEW"},
        {"gate": "gate2", "action": "SANITIZE", "replacement_content": None},
        {
            "gate": "gate0",
            "action": "SANITIZE",
            "tool_call_id": None,
            "replacement_content": "safe",
        },
    ],
)
def test_unknown_or_gate_inapplicable_decisions_rejected(decision_data, changes):
    from agentguard.contracts import SecurityDecision

    decision_data.update(changes)
    with pytest.raises(ValidationError):
        SecurityDecision(**decision_data)


def test_sanitize_requires_explicit_replacement_and_gate0_has_no_call(decision_data):
    from agentguard.contracts import SecurityDecision

    decision_data.update(gate="gate2", action="SANITIZE", replacement_content={"text": "safe"})
    safe = SecurityDecision(**decision_data)
    assert safe.replacement_content == {"text": "safe"}
    decision_data.update(gate="gate0", action="BLOCK", replacement_content=None, tool_call_id=None)
    assert SecurityDecision(**decision_data).tool_call_id is None


@pytest.mark.parametrize("severity", ["info", "low", "medium", "high", "critical"])
def test_findings_serialize_as_evidence_references(decision_data, severity):
    from agentguard.contracts import SecurityDecision, SecurityFinding

    finding = SecurityFinding(
        code="fixture.injection",
        severity=severity,
        evidence_ref="evidence.1",
        detector_id="fixture.detector",
    )
    decision_data["findings"] = [finding]
    decision_data["matched_policies"] = ["fixture.policy"]
    decision = SecurityDecision(**decision_data)
    assert SecurityDecision.model_validate_json(decision.model_dump_json()) == decision
    assert decision.findings[0].evidence_ref == "evidence.1"


@pytest.mark.parametrize(
    "change",
    [{"severity": "urgent"}, {"evidence_ref": ""}, {"raw_content": "unnecessary-private-text"}],
)
def test_invalid_finding_and_raw_evidence_field_are_rejected(change):
    from agentguard.contracts import SecurityFinding

    data = {
        "code": "fixture",
        "severity": "low",
        "evidence_ref": "evidence.1",
        "detector_id": "fixture.detector",
        **change,
    }
    with pytest.raises(ValidationError):
        SecurityFinding(**data)
