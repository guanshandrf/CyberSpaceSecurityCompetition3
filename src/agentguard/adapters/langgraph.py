"""Optional LangGraph bridge. Only safe ToolMessages leave the protected tool node."""

import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from threading import Lock
from uuid import uuid4

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from pydantic import PrivateAttr

from agentguard.contracts import (
    SecurityContext,
    SecurityDecision,
    ToolCallEvent,
    validate_correlation,
)
from agentguard.executor import ExecutionResult, GuardedExecutor, ResultHandler
from agentguard.registry import ToolRegistry

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z", re.ASCII)


class _InvalidCall(ValueError):
    def __init__(self, event, context, decision, original_id):
        super().__init__("Invalid framework tool call or backend context")
        self.event, self.context, self.decision = event, context, decision
        self.original_id = original_id


class _GuardedTool(BaseTool):
    """Agent-visible metadata and guarded callback; never stores a raw callable."""

    _bridge: object = PrivateAttr()

    def invoke(self, input, config=None, **kwargs):
        if type(input) is dict and input.get("type") == "tool_call":
            return self._bridge(input)
        message = self._bridge({"name": self.name, "args": input, "id": "call." + uuid4().hex})
        return message.content

    async def ainvoke(self, input, config=None, **kwargs):
        return await asyncio.to_thread(self.invoke, input, config, **kwargs)

    def _run(self, *args, run_manager=None, **kwargs):
        if args:
            raise ValueError("Structured tool arguments required")
        return self.invoke(kwargs)


class LangGraphAdapter:
    """One backend-owned execution session, registry, budget and replay ledger.

    registration_context is a catalog administrator, context is the requester's
    authorization. Neither may come from model arguments. Framework config is
    deliberately ignored as an authorization source. Use tools() AND tool_node()
    instead of retaining the original framework tools in a protected graph.
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
    ):
        # Revalidate backend provenance without manufacturing a new trusted context.
        if (
            type(context) is not SecurityContext
            or type(registration_context) is not SecurityContext
            or not context.has_backend_provenance()
            or not registration_context.has_backend_provenance()
            or context.session_id != registration_context.session_id
        ):
            raise ValueError("Backend contexts required")
        self._context = context
        self._context_lock = Lock()
        self._renewal_lock = Lock()
        self._audit = audit
        self._registry = ToolRegistry(audit=audit, gate=gate0, ttl=registration_ttl)
        self._registrations = {}
        bindings = tuple(bindings)
        if len({b.name for b in bindings}) != len(bindings):
            raise ValueError("Duplicate tool names")
        for binding in bindings:
            result = self._registry.register(
                binding, registration_context, description=descriptions[binding.name]
            )
            self._registrations[binding.name] = result
        self._executor = GuardedExecutor(
            [], audit=audit, registry=self._registry, policy=policy, detectors=detectors
        )
        self._executor.update_context(context)
        self._results = ResultHandler(audit=audit, gate=gate2)

    @property
    def registrations(self):
        """Backend observability only; approval tokens must never be sent to models."""
        return tuple(self._registrations.values())

    def refresh_registrations(self, registration_context):
        """Backend-only renewal using current catalog authority; never called by invoke.

        Only expired approvals are eligible. Gate0 reruns; revocation, REVIEW,
        denial and metadata/version changes cannot be silently revived.
        The same Executor retains all budgets, pending approvals and replay state.
        """
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
        """Trusted backend revocation; refresh cannot reverse it."""
        self._registry.revoke(tool_id, context=registration_context)

    def update_context(self, context):
        """Publish backend revocation through the executor's atomic revision check."""
        with self._context_lock:
            if (
                type(context) is not SecurityContext
                or context.session_id != self._context.session_id
            ):
                raise ValueError("Matching backend context required")
            self._executor.update_context(context)
            self._context = context

    def _context_snapshot(self):
        with self._context_lock:
            return self._context

    def call_event(self, call, *, trace_id):
        """Normalize model fields only; identity/digest/context always come from backend."""
        return self._call_event(call, trace_id=trace_id, context=self._context_snapshot())

    def _call_event(self, call, *, trace_id, context):
        try:
            if type(call) is not dict or set(call) - {"name", "args", "id", "type"}:
                raise ValueError
            if "type" in call and call["type"] != "tool_call":
                raise ValueError
            registration = self._registrations.get(call["name"])
            event = ToolCallEvent(
                schema_version="1.0",
                event_type="tool_call",
                event_id="call_event." + uuid4().hex,
                timestamp=datetime.now(UTC),
                trace_id=trace_id,
                session_id=context.session_id,
                tool_id=registration.event.tool_id if registration else "unknown.tool",
                name=call["name"],
                metadata_digest=registration.event.metadata_digest if registration else "0" * 64,
                tool_call_id=call["id"],
                arguments=call["args"],
                source="adapter.langgraph",
                context_ref=context.context_id,
            )
            validate_correlation(event, context=context)
            return event
        except Exception:
            raise ValueError("Invalid framework tool call or backend context") from None

    def invoke(self, call, *, trace_id):
        # Snapshot context for this call. Concurrent backend changes are also checked
        # by the executor; result correlation stays bound to its originating context.
        context = self._context_snapshot()
        try:
            event = self._call_event(call, trace_id=trace_id, context=context)
        except ValueError:
            raise self._invalid_call(call, trace_id=trace_id, context=context) from None
        execution = self._executor.execute(event, context)
        handled = self._results.handle_execution(execution, context, call=event)
        safe = handled.safe_event
        return ToolMessage(
            content=json.dumps(safe.content, ensure_ascii=False, allow_nan=False),
            name=event.name,
            tool_call_id=event.tool_call_id,
            status="error" if safe.is_error else "success",
            additional_kwargs={"agentguard": {"source": safe.source, "trace_id": event.trace_id}},
        )

    def _invalid_call(self, call, *, trace_id, context):
        def identifier(value, fallback):
            if type(value) is str and _IDENTIFIER.fullmatch(value):
                return value
            if type(value) is str:
                return (
                    fallback
                    + "."
                    + hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()
                )
            return fallback

        original_id = call.get("id") if type(call) is dict else None
        # This synthetic envelope describes rejection only, not a repaired executable
        # request. Raw args/name are never copied to audit, findings or error text.
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
            tool_call_id=identifier(original_id, "invalid.call"),
            arguments={},
            source="adapter.langgraph",
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
            recorder = getattr(self._audit, "append_invalid_call", None)
            if callable(recorder):
                recorder(decision, tool_call_id=original_id)
            else:
                self._audit.append(decision, stage="denied", duration_ms=0.0)
        except Exception:
            raise ValueError("Invalid framework tool call audit failed") from None
        return _InvalidCall(event, context, decision, original_id)

    def dispatch(self, call, *, trace_id):
        """Model-facing recovery; strict backend invoke() still rejects bad envelopes."""
        try:
            return self.invoke(call, trace_id=trace_id)
        except _InvalidCall as exc:
            if not self._recoverable_id(exc.original_id):
                raise
            handled = self._results.handle_execution(
                ExecutionResult(exc.decision), exc.context, call=exc.event
            )
            return ToolMessage(
                content=json.dumps(handled.safe_event.content, ensure_ascii=False),
                tool_call_id=exc.original_id,
                name="invalid.tool",
                status="error",
                additional_kwargs={
                    "agentguard": {
                        "source": handled.safe_event.source,
                        "trace_id": exc.event.trace_id,
                    }
                },
            )

    @staticmethod
    def _recoverable_id(value):
        if type(value) is not str or not 0 < len(value) <= 4096:
            return False
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            return False
        return True

    def validate_batch_ids(self, calls, *, trace_id):
        """Before graph history/streaming, reject IDs that cannot form a message pair."""
        seen = set()
        for call in calls:
            call_id = call.get("id") if type(call) is dict else None
            if not self._recoverable_id(call_id) or call_id in seen:
                raise self._invalid_call(call, trace_id=trace_id, context=self._context_snapshot())
            seen.add(call_id)

    def dispatch_many(self, calls, *, trace_id):
        """Preflight protocol correlation before any batch side effect."""
        calls = tuple(calls)
        self.validate_batch_ids(calls, trace_id=trace_id)
        return [self.dispatch(call, trace_id=trace_id) for call in calls]

    def tools(self, *, trace_id):
        """Only current Gate0-approved metadata/wrappers are exposed to the model."""
        tools = []
        for binding in self._registry.bindings():
            registration = self._registrations[binding.name]
            wrapper = _GuardedTool(
                name=binding.name,
                description=registration.event.description,
                args_schema=binding.parameters_schema,
            )
            # Capture no binding or handler in the callback.
            wrapper._bridge = lambda call: self.dispatch(call, trace_id=trace_id)
            tools.append(wrapper)
        return tuple(tools)

    def tool_node(self, *, trace_id):
        """StateGraph-compatible node; errors never fall back to raw invocation."""

        def node(state):
            return {
                "messages": self.dispatch_many(
                    [*state["messages"][-1].tool_calls, *state["messages"][-1].invalid_tool_calls],
                    trace_id=trace_id,
                )
            }

        return node


def protect(bindings, **options):
    """Build a protected tool facade for a StateGraph; see docs/langgraph.md."""
    return LangGraphAdapter(bindings, **options)
