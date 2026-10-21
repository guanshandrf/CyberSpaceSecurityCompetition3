"""Registration policy only; the registry binds metadata, callable and live admission."""

from agentguard.contracts import SecurityDecision, ToolRegistrationEvent, parse_event
from agentguard.detectors.registration import RegistrationDetector
from agentguard.gates.gate1 import trusted_snapshot
from agentguard.policies.schema import validate_schema


def registration_decision(event, action, reason, *, findings=()):
    return SecurityDecision(
        schema_version="1.0",
        gate="gate0",
        event_id=event.event_id,
        trace_id=event.trace_id,
        session_id=event.session_id,
        tool_id=event.tool_id,
        action=action,
        reason_codes=(reason,),
        matched_policies=("policy.registration",),
        findings=findings,
    )


class Gate0:
    gate_id = "gate0"

    def __init__(
        self,
        *,
        allowed_sources=("backend.local",),
        blocked_capabilities=("system.exec", "network.external"),
    ):
        self._sources = frozenset(allowed_sources)
        self._blocked = frozenset(blocked_capabilities)
        if not self._sources:
            raise ValueError("Explicit tool sources required")

    def evaluate(self, event, context):
        event = parse_event(event)
        if type(event) is not ToolRegistrationEvent:
            raise ValueError("Registration event required")
        try:
            context = trusted_snapshot(context)
            if event.session_id != context.session_id or "tool.register" not in context.permissions:
                return registration_decision(event, "BLOCK", "registry.permission")
            if not set(event.permissions).issubset(context.permissions):
                return registration_decision(event, "BLOCK", "registry.permission")
            if event.source not in self._sources:
                return registration_decision(event, "BLOCK", "registry.source")
            if self._blocked.intersection(event.capabilities):
                return registration_decision(event, "BLOCK", "registry.capability")
            if not event.description.strip():
                return registration_decision(event, "BLOCK", "registry.metadata")
            validate_schema(event.parameters_schema)
            findings = RegistrationDetector().detect(event, context)
            return registration_decision(
                event,
                "REVIEW" if findings else "ALLOW",
                "registry.review" if findings else "registry.allowed",
                findings=findings,
            )
        except Exception:
            return registration_decision(event, "BLOCK", "check.failed")
