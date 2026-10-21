"""Deterministic configurable decisions; hard checks live in Gate 1."""

from dataclasses import dataclass

from agentguard.contracts import SecurityDecision


def decision_for(event, action, reason, *, findings=(), policies=()):
    return SecurityDecision(
        schema_version="1.0",
        gate="gate1",
        event_id=event.event_id,
        trace_id=event.trace_id,
        session_id=event.session_id,
        tool_id=event.tool_id,
        tool_call_id=event.tool_call_id,
        action=action,
        reason_codes=(reason,),
        findings=findings,
        matched_policies=policies,
    )


@dataclass(frozen=True)
class PolicyEngine:
    blocked_tools: frozenset[str] = frozenset()
    review_tools: frozenset[str] = frozenset()
    policy_id: str = "policy.configured"

    def __post_init__(self):
        object.__setattr__(self, "blocked_tools", frozenset(self.blocked_tools))
        object.__setattr__(self, "review_tools", frozenset(self.review_tools))

    def evaluate(self, event, context, findings):
        if event.tool_id in self.blocked_tools or findings:
            action, reason = "BLOCK", "policy.denied"
        elif event.tool_id in self.review_tools:
            action, reason = "REVIEW", "approval.required"
        else:
            action, reason = "ALLOW", "checks.passed"
        return decision_for(event, action, reason, findings=findings, policies=(self.policy_id,))
