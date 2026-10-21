"""Gate 2 decisions with result source and call/context validation."""

from agentguard.contracts import (
    SecurityDecision,
    SecurityFinding,
    ToolResultEvent,
    parse_event,
    validate_correlation,
)
from agentguard.detectors import Redactor, RuleResultDetector
from agentguard.gates.gate1 import trusted_snapshot


def result_decision(event, action, reason, *, replacement=None, findings=()):
    return SecurityDecision(
        schema_version="1.0",
        gate="gate2",
        event_id=event.event_id,
        trace_id=event.trace_id,
        session_id=event.session_id,
        tool_id=event.tool_id,
        tool_call_id=event.tool_call_id,
        action=action,
        reason_codes=(reason,),
        findings=findings,
        matched_policies=("policy.result",),
        replacement_content=replacement,
    )


class Gate2:
    gate_id = "gate2"

    def __init__(self, *, detectors=(), redactor=None):
        self._detectors = (RuleResultDetector(), *tuple(detectors))
        self._redactor = Redactor() if redactor is None else redactor

    def evaluate(self, event, context):
        event = parse_event(event)
        if type(event) is not ToolResultEvent:
            raise ValueError("Gate 2 requires a result event")
        try:
            context = trusted_snapshot(context)
            if event.session_id != context.session_id:
                raise ValueError("Context mismatch")
            findings = []
            for detector in self._detectors:
                output = detector.detect(parse_event(event), trusted_snapshot(context))
                if type(output) is not tuple:
                    raise ValueError("Invalid detector output")
                for finding in output:
                    if type(finding) is not SecurityFinding:
                        raise ValueError("Invalid finding")
                    findings.append(
                        SecurityFinding.model_validate(
                            {name: getattr(finding, name) for name in SecurityFinding.model_fields}
                        )
                    )
            if findings:
                return result_decision(
                    event, "BLOCK", "result.instruction", findings=tuple(findings)
                )
            replacement = self._redactor.redact(parse_event(event).content)
            if replacement != event.content:
                return result_decision(
                    event, "SANITIZE", "result.redacted", replacement=replacement
                )
            return result_decision(event, "ALLOW", "result.passed")
        except Exception:
            return result_decision(event, "BLOCK", "check.failed")

    def after_tool(self, event, context, *, call):
        event = parse_event(event)
        if type(event) is not ToolResultEvent:
            raise ValueError("Gate 2 requires a result event")
        try:
            validate_correlation(event, context=trusted_snapshot(context), call=call)
        except Exception:
            return result_decision(event, "BLOCK", "result.correlation")
        return self.evaluate(event, context)
