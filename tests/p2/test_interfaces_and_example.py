import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.p2
ROOT = Path(__file__).resolve().parents[2]


def test_framework_free_structural_detector_policy_gate_contracts(
    call_data, decision_data, backend_context
):
    from agentguard.contracts import (
        Detector,
        Gate,
        Policy,
        SecurityDecision,
        SecurityFinding,
        parse_event,
        validate_correlation,
    )

    class FixtureDetector:
        detector_id = "fixture.detector"

        def detect(self, event, context):
            return (
                SecurityFinding(
                    code="fixture.only",
                    severity="low",
                    evidence_ref="fixture.evidence",
                    detector_id=self.detector_id,
                ),
            )

    class FixturePolicy:
        policy_id = "fixture.policy"

        def evaluate(self, event, context, findings):
            return SecurityDecision(**{**decision_data, "findings": findings})

    class FixtureGate:
        gate_id = "gate1"

        def evaluate(self, event, context):
            decision = FixturePolicy().evaluate(
                event, context, FixtureDetector().detect(event, context)
            )
            validate_correlation(event, context=context, decision=decision)
            return decision

    assert isinstance(FixtureDetector(), Detector)
    assert isinstance(FixturePolicy(), Policy)
    assert isinstance(FixtureGate(), Gate)
    result = FixtureGate().evaluate(parse_event(call_data), backend_context)
    assert result.action.value == "BLOCK"
    assert result.findings[0].detector_id == "fixture.detector"
    for interface in (Detector, Policy, Gate):
        with pytest.raises(TypeError):
            interface()


def test_mock_adapter_normalizes_three_events_without_tool_execution():
    from agentguard.contracts import parse_event

    completed = subprocess.run(
        [sys.executable, str(ROOT / "examples/mock_adapter.py")],
        cwd=ROOT,
        env=dict(os.environ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["synthetic"] is True
    assert result["tool_executions"] == 0
    assert result["guard_enforced"] is False
    assert [parse_event(event).event_type for event in result["events"]] == [
        "tool_registration",
        "tool_call",
        "tool_result",
    ]
