"""Gate 1 checks are advisory until enforced atomically by GuardedExecutor."""

from contextlib import nullcontext
from types import MappingProxyType

from agentguard.contracts import (
    SecurityContext,
    SecurityDecision,
    SecurityFinding,
    ToolCallEvent,
    parse_event,
    validate_correlation,
)
from agentguard.policies import PolicyEngine, ToolBinding
from agentguard.policies.engine import decision_for
from agentguard.policies.schema import matches_schema


def trusted_snapshot(context):
    if type(context) is not SecurityContext or not context.has_backend_provenance():
        raise ValueError("A trusted backend context is required")
    return SecurityContext.from_backend(
        **{name: getattr(context, name) for name in SecurityContext.model_fields}
    )


def call_snapshot(event):
    try:
        call = parse_event(event)
        if type(call) is not ToolCallEvent:
            raise ValueError
        return call
    except Exception:
        raise ValueError("Invalid Gate 1 call event") from None


class Gate1:
    gate_id = "gate1"

    def __init__(self, tools, *, policy=None, detectors=(), registry=None):
        bindings = tuple(tools)
        if any(type(tool) is not ToolBinding for tool in bindings):
            raise ValueError("Only backend tool bindings are accepted")
        if len({tool.tool_id for tool in bindings}) != len(bindings):
            raise ValueError("Duplicate tool ID")
        self.tools = MappingProxyType({tool.tool_id: tool for tool in bindings})
        self.policy = PolicyEngine() if policy is None else policy
        self.detectors = tuple(detectors)
        if registry is not None:
            from agentguard.registry import ToolRegistry

            if type(registry) is not ToolRegistry:
                raise ValueError("A backend ToolRegistry is required")
        self.registry = registry

    def binding_for(self, call):
        return (
            self.registry.binding_for(call)
            if self.registry is not None
            else self.tools.get(call.tool_id)
        )

    def admission_stamp(self, call):
        return self.registry.stamp(call) if self.registry is not None else None

    def execution_guard(self, call, stamp):
        return (
            self.registry.execution_guard(call, stamp)
            if self.registry is not None
            else nullcontext(self.binding_for(call))
        )

    def prepare(self, call, context):
        """Return hard-denial code and fresh canonical handler arguments."""
        try:
            context = trusted_snapshot(context)
            validate_correlation(call, context=context)
        except Exception:
            return "context.invalid", None
        try:
            tool = self.binding_for(call)
        except ValueError as exc:
            return getattr(exc, "reason", "registry.denied"), None
        if tool is None:
            return "tool.unknown", None
        if call.name != tool.name or (
            self.registry is None and call.metadata_digest != tool.metadata_digest
        ):
            return "tool.mismatch", None
        if context.task_authorization not in tool.task_authorizations:
            return "task.denied", None
        if not set(tool.permissions).issubset(context.permissions):
            return "permission.denied", None
        resources = {*tool.resources, *(rule.resource_id for rule in tool.paths)}
        if not resources.issubset(context.allowed_resources):
            return "resource.denied", None
        if context.budget.calls_used >= context.budget.max_calls:
            return "budget.exhausted", None
        if not matches_schema(call.arguments, tool.parameters_schema):
            return "schema.invalid", None
        arguments = call_snapshot(call).arguments
        try:
            for rule in tool.paths:
                arguments[rule.parameter] = rule.resolve_argument(arguments[rule.parameter])
        except Exception:
            return "path.denied", None
        return None, arguments

    def before_tool(self, event, context):
        call = call_snapshot(event)
        try:
            reason, _ = self.prepare(call, context)
            if reason:
                return decision_for(call, "BLOCK", reason)
            context = trusted_snapshot(context)
            findings = []
            for detector in self.detectors:
                output = detector.detect(call_snapshot(call), trusted_snapshot(context))
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
            findings = tuple(findings)
            decision = self.policy.evaluate(
                call_snapshot(call), trusted_snapshot(context), findings
            )
            if type(decision) is not SecurityDecision:
                raise ValueError("Invalid policy decision")
            # Revalidate policy output before checking its event association.
            decision = SecurityDecision.model_validate(
                {name: getattr(decision, name) for name in SecurityDecision.model_fields}
            )
            validate_correlation(call, context=context, decision=decision)
            if decision.action == "ALLOW" and self.binding_for(call).requires_review:
                return decision_for(call, "REVIEW", "approval.required", findings=decision.findings)
            return decision
        except Exception:
            return decision_for(call, "BLOCK", "check.failed")

    def evaluate(self, event, context):
        return self.before_tool(event, context)
