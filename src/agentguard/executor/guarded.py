"""Process-local authorization: bounded approvals and short shared-state critical sections."""

import hashlib
import secrets
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field

from agentguard.contracts import SecurityContext, SecurityDecision, validate_correlation
from agentguard.gates import Gate1
from agentguard.gates.gate1 import call_snapshot, trusted_snapshot
from agentguard.policies.engine import decision_for
from agentguard.policies.schema import canonical


@dataclass(frozen=True)
class ExecutionResult:
    decision: SecurityDecision | None = field(repr=False)
    executed: bool = False
    value: object = field(default=None, repr=False)
    error_code: str | None = None
    approval_ref: str | None = field(default=None, repr=False)


@dataclass
class _Pending:
    fingerprint: str
    expires: float
    decision: SecurityDecision
    state: str = "pending"
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32), repr=False)


@dataclass
class _Session:
    user: str
    used: int
    limit: int
    pending: int = 0
    revision: int = 0
    context: SecurityContext | None = field(default=None, repr=False)
    lock: object = field(default_factory=threading.Lock, repr=False)


class _Denied(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


class GuardedExecutor:
    """Detectors/policies run without executor locks; final admission is per session.

    The global lock protects only maps/counters, never filesystem, plugins or audit.
    Backend revocations use update_context(). Already-started effects cannot be undone.
    Restart/multiprocess persistence and OS-level handler isolation are outside P3.
    """

    def __init__(
        self,
        tools,
        *,
        audit,
        policy=None,
        detectors=(),
        approval_ttl=300.0,
        max_pending_approvals=1024,
        max_pending_per_session=None,
        max_approval_creations=256,
        approval_window=60.0,
        registry=None,
    ):
        for value in (approval_ttl, approval_window):
            if type(value) not in (int, float) or not 0 < value <= 3600:
                raise ValueError("Approval time limits must be 0..3600 seconds")
        if type(max_pending_approvals) is not int:
            raise ValueError("Approval count limits must be positive bounded integers")
        if max_pending_per_session is None:
            max_pending_per_session = min(64, max_pending_approvals)
        for value in (max_pending_approvals, max_pending_per_session, max_approval_creations):
            if type(value) is not int or not 1 <= value <= 1_000_000:
                raise ValueError("Approval count limits must be positive bounded integers")
        if not callable(getattr(audit, "append", None)):
            raise ValueError("A working audit sink is required")
        self.gate = Gate1(tools, policy=policy, detectors=detectors, registry=registry)
        self._audit = audit
        self._ttl = approval_ttl
        self._max_pending = max_pending_approvals
        self._max_session_pending = max_pending_per_session
        self._max_creations = max_approval_creations
        self._approval_window = approval_window
        self._lock = threading.Lock()
        self._sessions = {}
        self._used_calls = set()
        self._used_events = set()
        # Fixed TTL makes insertion order identical to expiry order.
        self._pending = OrderedDict()
        self._approval_tokens = {}
        self._creation_times = deque()

    def before_tool(self, event, context):
        return self.gate.before_tool(event, context)

    def _record(self, decision, stage, started):
        self._audit.append(decision, stage=stage, duration_ms=(time.monotonic() - started) * 1000)

    def _stop(self, call, reason, started):
        decision = decision_for(call, "BLOCK", reason)
        try:
            self._record(decision, "denied", started)
        except Exception:
            decision = decision_for(call, "BLOCK", "audit.failed")
        return ExecutionResult(decision)

    def _session(self, context):
        """Bookkeeping helpers require _lock and call no plugins, audit or filesystem."""
        session = self._sessions.get(context.session_id)
        if session is None:
            session = _Session(context.user_id, context.budget.calls_used, context.budget.max_calls)
            self._sessions[context.session_id] = session
        if session.user != context.user_id:
            raise _Denied("session.mismatch")
        session.used = max(session.used, context.budget.calls_used)
        session.limit = min(session.limit, context.budget.max_calls)
        return session

    def update_context(self, context):
        """Trusted backend only: publish current claims/revocations for this session.

        Replaces no P2 contract. Never expose as a model tool or accept untrusted claims.
        Updates linearize against final reservation, before the synchronous handler.
        """
        try:
            context = trusted_snapshot(context)
            with self._lock:
                session = self._session(context)
                session.context = context
                session.revision += 1
        except Exception:
            raise ValueError("Context update rejected") from None

    def _drop_pending(self, key):
        pending = self._pending.pop(key, None)
        if pending is not None:
            self._approval_tokens.pop(pending.token, None)
            self._sessions[key[0]].pending -= 1
        return pending

    def _cleanup(self, now):
        removed = 0
        while self._pending:
            key = next(iter(self._pending))
            if self._pending[key].expires > now:
                break
            self._drop_pending(key)
            removed += 1
        while self._creation_times and self._creation_times[0] <= now - self._approval_window:
            self._creation_times.popleft()
        return removed

    def cleanup_expired_approvals(self):
        """Idle cleanup hook; execute/approve also sweep expired entries automatically."""
        with self._lock:
            return self._cleanup(time.monotonic())

    def approve(self, approval_ref, *, approver, approved=True):
        """Backend-only approval. O(1) token lookup; audit never holds the global lock."""
        started = time.monotonic()
        try:
            approver = trusted_snapshot(approver)
            if (
                type(approved) is not bool
                or type(approval_ref) is not str
                or "guard.approve" not in approver.permissions
            ):
                raise ValueError
            with self._lock:
                self._cleanup(time.monotonic())
                key = self._approval_tokens.get(approval_ref)
                pending = self._pending.get(key)
                if (
                    pending is None
                    or pending.state != "pending"
                    or approver.session_id != pending.decision.session_id
                ):
                    raise ValueError
                pending.state = "approving"
            try:
                self._record(pending.decision, "approved" if approved else "rejected", started)
            except Exception:
                with self._lock:
                    if self._pending.get(key) is pending and pending.state == "approving":
                        pending.state = "pending"
                raise
            with self._lock:
                self._cleanup(time.monotonic())
                if self._pending.get(key) is not pending:
                    raise ValueError
                pending.state = "approved" if approved else "denied"
        except Exception:
            raise ValueError("Approval rejected") from None

    def _check_call_state(self, call_key, event_key, session):
        if call_key in self._used_calls or event_key in self._used_events:
            raise _Denied("call.replayed")
        if session.used >= session.limit:
            raise _Denied("budget.exhausted")

    def _pending_for(self, call, session, fingerprint, decision):
        key = (call.session_id, call.tool_call_id)
        now = time.monotonic()
        pending = self._pending.get(key)
        expired = pending is not None and pending.expires <= now
        self._cleanup(now)
        if expired:
            raise _Denied("approval.expired")
        pending = self._pending.get(key)
        if pending:
            if pending.fingerprint != fingerprint:
                raise _Denied("approval.mismatch")
            if pending.state == "denied":
                raise _Denied("approval.denied")
        if decision.action == "REVIEW" and pending is None:
            if (
                len(self._pending) >= self._max_pending
                or session.pending >= self._max_session_pending
            ):
                raise _Denied("approval.capacity")
            if len(self._creation_times) >= self._max_creations:
                raise _Denied("approval.rate_limited")
            pending = _Pending(fingerprint, now + self._ttl, decision)
            self._pending[key] = pending
            self._approval_tokens[pending.token] = key
            session.pending += 1
            self._creation_times.append(now)
        return pending

    def _authorize(self, call, context, session, revision, decision, started):
        """Only same-session finalization waits; expensive analysis already finished."""
        call_key = (call.session_id, call.tool_call_id)
        event_key = (call.session_id, call.event_id)
        with session.lock:
            stamp = self.gate.admission_stamp(call)
            with self._lock:
                current = session.context if session.context is not None else context
                changed = session.revision != revision
            reason, arguments = self.gate.prepare(call, current)
            if reason:
                raise _Denied(reason)
            if changed:
                raise _Denied("context.changed")
            fingerprint = hashlib.sha256(
                canonical(
                    {
                        "call": call.model_dump(mode="json"),
                        "context": current.model_dump(mode="json"),
                        "admission": stamp,
                    }
                ).encode("utf-8")
            ).hexdigest()
            with self._lock:
                self._check_call_state(call_key, event_key, session)
                pending = self._pending_for(call, session, fingerprint, decision)
            if pending is not None and pending.state != "approved":
                review = decision_for(call, "REVIEW", "approval.required")
                self._record(review, "review", started)
                return ExecutionResult(review, approval_ref=pending.token)
            if pending is not None:
                decision = decision_for(call, "ALLOW", "approval.approved")
            reason, arguments = self.gate.prepare(call, current)
            if reason:
                raise _Denied(reason)
            self._record(decision, "started", started)  # Intent only; audit failure => zero calls.
            with self.gate.execution_guard(call, stamp) as binding:
                reason, arguments = self.gate.prepare(call, current)
                if reason:
                    raise _Denied(reason)
                with self._lock:
                    if session.revision != revision:
                        raise _Denied("context.changed")
                    self._check_call_state(call_key, event_key, session)
                    if pending is not None:
                        self._cleanup(time.monotonic())
                        if self._pending.get(call_key) is not pending:
                            raise _Denied("approval.expired")
                        if pending.state != "approved":
                            raise _Denied("approval.required")
                    self._used_calls.add(call_key)
                    self._used_events.add(event_key)
                    session.used += 1
                    self._drop_pending(call_key)
                return decision, arguments, binding._handler

    def execute(self, event, context):
        started = time.monotonic()
        try:
            call = call_snapshot(event)
        except Exception:
            return ExecutionResult(None, error_code="event.invalid")
        try:
            context = trusted_snapshot(context)
            validate_correlation(call, context=context)
        except Exception:
            return self._stop(call, "context.invalid", started)
        try:
            with self._lock:
                session = self._session(context)
                key = (call.session_id, call.tool_call_id)
                prior = self._pending.get(key)
                expired = prior is not None and prior.expires <= time.monotonic()
                self._cleanup(time.monotonic())
                current = session.context if session.context is not None else context
                revision = session.revision
            if expired:
                raise _Denied("approval.expired")
            # No global or session lock is held during detector/policy extension code.
            decision = self.gate.before_tool(call, current)
            if decision.action == "BLOCK":
                self._record(decision, "denied", started)
                return ExecutionResult(decision)
            authorization = self._authorize(call, current, session, revision, decision, started)
            if isinstance(authorization, ExecutionResult):
                return authorization
            decision, arguments, handler = authorization
        except _Denied as exc:
            return self._stop(call, exc.reason, started)
        except Exception:
            return self._stop(call, "check.failed", started)
        try:
            value = handler(**arguments)
        except Exception:
            value, error = None, "tool.failed"
        else:
            error = None
        try:
            self._record(decision, "error" if error else "completed", started)
        except Exception:
            return ExecutionResult(
                decision, executed=True, error_code="audit.failed_after_execution"
            )
        return ExecutionResult(decision, executed=True, value=value, error_code=error)
