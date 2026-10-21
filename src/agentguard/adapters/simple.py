"""Framework-free facade for backend-owned, plain Python agent loops."""

import hashlib
import re
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Lock
from uuid import uuid4

from agentguard.contracts import (
    SecurityContext,
    SecurityDecision,
    ToolCallEvent,
    ToolResultEvent,
    validate_correlation,
)
from agentguard.executor import ExecutionResult, GuardedExecutor, ResultHandler
from agentguard.registry import ToolRegistry

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z", re.ASCII)


@dataclass(frozen=True)
class SafeReply:
    safe_event: ToolResultEvent = field(repr=False)
    executed: bool
    gate1_action: str
    gate2_action: str
    approval_ref: str | None = field(default=None, repr=False)


class SimpleAdapter:
    """One execution session; model input never supplies backend authority.

    tools()/invoke() are model-facing. All other methods are trusted backend APIs.
    Approval retries require the exact event retained from call_event().
    """

    def __init__(
        self,
        bindings,
        *,
        descriptions,
        context,
        registration_context,
        audit,
        gate0=None,
        gate2=None,
        policy=None,
        detectors=(),
        registration_ttl=300.0,
        approval_ttl=300.0,
        max_pending_approvals=1024,
    ):
        if (
            type(context) is not SecurityContext
            or type(registration_context) is not SecurityContext
            or not context.has_backend_provenance()
            or not registration_context.has_backend_provenance()
            or context.session_id != registration_context.session_id
        ):
            raise ValueError("Backend contexts required")
        self._context, self._audit = context, audit
        self._lock, self._renewal_lock = Lock(), Lock()
        self._registry = ToolRegistry(audit=audit, gate=gate0, ttl=registration_ttl)
        bindings = tuple(bindings)
        if len({b.name for b in bindings}) != len(bindings):
            raise ValueError("Duplicate tool names")
        self._registrations = {
            b.name: self._registry.register(
                b, registration_context, description=descriptions[b.name]
            )
            for b in bindings
        }
        self._executor = GuardedExecutor(
            [],
            audit=audit,
            registry=self._registry,
            policy=policy,
            detectors=detectors,
            approval_ttl=approval_ttl,
            max_pending_approvals=max_pending_approvals,
        )
        self._executor.update_context(context)
        self._results = ResultHandler(audit=audit, gate=gate2)

    def _snapshot(self):
        with self._lock:
            return self._context

    def tools(self):
        """Fresh metadata copies only; never expose raw bindings or handlers."""
        with self._renewal_lock:
            return tuple(
                {
                    "name": b.name,
                    "description": self._registrations[b.name].event.description,
                    "parameters": deepcopy(b.parameters_schema),
                }
                for b in self._registry.bindings()
            )

    def update_context(self, context):
        with self._lock:
            if (
                type(context) is not SecurityContext
                or context.user_id != self._context.user_id
                or context.session_id != self._context.session_id
            ):
                raise ValueError("Matching backend context required")
            self._executor.update_context(context)
            self._context = context

    def refresh_registrations(self, registration_context):
        renewed = []
        with self._renewal_lock:
            for name, old in tuple(self._registrations.items()):
                if old.decision.action != "ALLOW":
                    continue
                result = self._registry.renew(
                    old.event.tool_id,
                    registration_context,
                    expected_digest=old.event.metadata_digest,
                    expected_version=old.event.version,
                )
                if result is not None:
                    self._registrations[name] = result
                    renewed.append(result)
        return tuple(renewed)

    def revoke(self, tool_id, *, registration_context):
        self._registry.revoke(tool_id, context=registration_context)

    def approve(self, approval_ref, *, approver, approved=True):
        return self._executor.approve(approval_ref, approver=approver, approved=approved)

    def call_event(self, request, *, trace_id):
        return self._call_event(request, trace_id, self._snapshot())

    def _call_event(self, request, trace_id, context):
        try:
            if type(request) is not dict or set(request) != {"name", "arguments", "tool_call_id"}:
                raise ValueError
            with self._renewal_lock:
                registration = self._registrations.get(request["name"])
            event = ToolCallEvent(
                schema_version="1.0",
                event_type="tool_call",
                event_id="call." + uuid4().hex,
                timestamp=datetime.now(UTC),
                trace_id=trace_id,
                session_id=context.session_id,
                tool_id=registration.event.tool_id if registration else "unknown.tool",
                name=request["name"],
                metadata_digest=registration.event.metadata_digest if registration else "0" * 64,
                tool_call_id=request["tool_call_id"],
                arguments=request["arguments"],
                source="adapter.simple",
                context_ref=context.context_id,
            )
            validate_correlation(event, context=context)
            return event
        except Exception:
            raise ValueError("Invalid tool call") from None

    def invoke(self, request, *, trace_id):
        context = self._snapshot()
        try:
            event = self._call_event(request, trace_id, context)
        except ValueError:
            return self._invalid(request, trace_id, context)
        return self._execute(event, context)

    def execute(self, event):
        """Backend-only approval retry; Executor revalidates the whole event."""
        return self._execute(event, self._snapshot())

    def _execute(self, event, context):
        validate_correlation(event, context=context)
        execution = self._executor.execute(event, context)
        return self._handle(execution, event, context)

    def _handle(self, execution, event, context):
        handled = self._results.handle_execution(execution, context, call=event)
        return SafeReply(
            handled.safe_event,
            execution.executed,
            execution.decision.action,
            handled.decision.action,
            execution.approval_ref,
        )

    def _invalid(self, request, trace_id, context):
        def identifier(value, fallback):
            if type(value) is str:
                if _ID.fullmatch(value):
                    return value
                return (
                    fallback
                    + "."
                    + hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()
                )
            return fallback

        event = ToolCallEvent(
            schema_version="1.0",
            event_type="tool_call",
            event_id="invalid." + uuid4().hex,
            timestamp=datetime.now(UTC),
            trace_id=identifier(trace_id, "invalid.trace"),
            session_id=context.session_id,
            tool_id="invalid.tool",
            name="invalid.tool",
            metadata_digest="0" * 64,
            tool_call_id=identifier(
                request.get("tool_call_id") if type(request) is dict else None, "invalid.call"
            ),
            arguments={},
            source="adapter.simple",
            context_ref=context.context_id,
        )
        decision = SecurityDecision(
            schema_version="1.0",
            gate="gate1",
            event_id=event.event_id,
            trace_id=event.trace_id,
            session_id=event.session_id,
            tool_id=event.tool_id,
            tool_call_id=event.tool_call_id,
            action="BLOCK",
            reason_codes=("event.invalid",),
        )
        try:
            self._audit.append(decision, stage="denied", duration_ms=0.0)
        except Exception:
            raise ValueError("Tool call audit failed") from None
        return self._handle(ExecutionResult(decision), event, context)
