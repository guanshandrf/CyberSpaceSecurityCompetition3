"""Bounded, versioned registration. An old decision is never a live registration grant."""

import hashlib
import secrets
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

from agentguard.contracts import (
    SecurityDecision,
    ToolRegistrationEvent,
    parse_event,
    validate_correlation,
)
from agentguard.gates.gate0 import Gate0, registration_decision
from agentguard.gates.gate1 import trusted_snapshot
from agentguard.policies import ToolBinding
from agentguard.policies.schema import canonical


class RegistryError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class RegistrationResult:
    event: ToolRegistrationEvent = field(repr=False)
    decision: SecurityDecision = field(repr=False)
    review_ref: str | None = field(default=None, repr=False)


@dataclass
class _Entry:
    binding: ToolBinding
    event: ToolRegistrationEvent = field(repr=False)
    generation: int
    expires: float
    state: str = "CHECKING"
    token: str | None = field(default=None, repr=False)


class ToolRegistry:
    def __init__(self, *, audit, gate=None, ttl=300.0, max_tools=128):
        if type(ttl) not in (int, float) or not 0 < ttl <= 3600:
            raise ValueError("Registry TTL must be 0..3600 seconds")
        if type(max_tools) is not int or not 1 <= max_tools <= 4096:
            raise ValueError("Registry capacity must be 1..4096")
        self._audit = audit
        self._gate = Gate0() if gate is None else gate
        self._ttl, self._capacity = ttl, max_tools
        self._lock = threading.RLock()
        self._entries, self._names, self._tokens = {}, {}, {}
        self._generation = 0

    def _record(self, decision):
        self._audit.append(decision, stage="registered", duration_ms=0.0)

    def register(
        self, binding, context, *, source="backend.local", description, version="1", capabilities=()
    ):
        return self._register(
            binding,
            context,
            source=source,
            description=description,
            version=version,
            capabilities=capabilities,
        )

    def renew(self, tool_id, context, *, expected_digest, expected_version):
        """Recheck an expired, formerly approved entry. Never resurrect revocation.

        The backend supplies CURRENT catalog authority and the metadata it expects;
        original binding/metadata are read from the registry, not from model input.
        A concurrent revoke/update wins over in-flight renewal.
        """
        context = trusted_snapshot(context)
        with self._lock:
            entry = self._entries.get(tool_id)
            if entry is None:
                raise RegistryError("registry.unknown")
            event = parse_event(entry.event)
            if context.session_id != event.session_id:
                reason = "registry.permission"
            elif expected_digest != event.metadata_digest or expected_version != event.version:
                reason = "registry.mismatch"
            elif entry.state not in {"ALLOW", "EXPIRED"}:
                reason = "registry.denied"
            elif time.monotonic() < entry.expires:
                return None
            else:
                reason = None
        if reason:
            rejected = registration_decision(event, "BLOCK", reason)
            self._record(rejected)
            return RegistrationResult(event, rejected)
        return self._register(
            entry.binding,
            context,
            source=event.source,
            description=event.description,
            version=event.version,
            capabilities=event.capabilities,
            previous=entry,
        )

    def _register(
        self, binding, context, *, source, description, version, capabilities, previous=None
    ):
        if type(binding) is not ToolBinding:
            raise ValueError("Backend tool binding required")
        context = trusted_snapshot(context)
        metadata = dict(
            tool_id=binding.tool_id,
            name=binding.name,
            source=source,
            description=description,
            version=version,
            parameters_schema=binding.parameters_schema,
            permissions=list(binding.permissions),
            capabilities=list(capabilities),
        )
        digest = hashlib.sha256(
            canonical({**metadata, "binding_digest": binding.metadata_digest}).encode("utf-8")
        ).hexdigest()
        event = ToolRegistrationEvent(
            **metadata,
            schema_version="1.0",
            event_type="tool_registration",
            event_id="registration." + uuid.uuid4().hex,
            trace_id="trace." + uuid.uuid4().hex,
            timestamp=datetime.now(UTC),
            session_id=context.session_id,
            metadata_digest=digest,
        )
        with self._lock:
            existing = self._entries.get(binding.tool_id)
            conflict = self._names.get(binding.name)
            if previous is not None and (
                existing is not previous
                or previous.state not in {"ALLOW", "EXPIRED"}
                or previous.event.metadata_digest != event.metadata_digest
                or previous.event.version != event.version
            ):
                rejected = registration_decision(event, "BLOCK", "registry.changed")
                entry = None
            elif (conflict is not None and conflict != binding.tool_id) or (
                existing is not None and existing.binding.name != binding.name
            ):
                rejected = registration_decision(event, "BLOCK", "registry.name_conflict")
                entry = None
            elif existing is None and len(self._entries) >= self._capacity:
                rejected = registration_decision(event, "BLOCK", "registry.capacity")
                entry = None
            else:
                if existing and existing.token:
                    self._tokens.pop(existing.token, None)
                self._generation += 1
                entry = _Entry(
                    binding, parse_event(event), self._generation, time.monotonic() + self._ttl
                )
                self._entries[binding.tool_id] = entry
                self._names[binding.name] = binding.tool_id
        if entry is None:
            try:
                self._record(rejected)
            except Exception:
                rejected = registration_decision(event, "BLOCK", "audit.failed")
            return RegistrationResult(event, rejected)
        try:
            decision = self._gate.evaluate(parse_event(event), trusted_snapshot(context))
            decision = SecurityDecision.model_validate(
                {name: getattr(decision, name) for name in SecurityDecision.model_fields}
            )
            validate_correlation(event, context=context, decision=decision)
            self._record(decision)
        except Exception:
            decision = registration_decision(event, "BLOCK", "check.failed")
        with self._lock:
            if self._entries.get(binding.tool_id) is not entry or entry.state != "CHECKING":
                return RegistrationResult(
                    event, registration_decision(event, "BLOCK", "registry.changed")
                )
            if time.monotonic() >= entry.expires:
                decision = registration_decision(event, "BLOCK", "registry.expired")
            entry.state = decision.action.value
            if entry.state == "REVIEW":
                entry.token = secrets.token_urlsafe(32)
                self._tokens[entry.token] = binding.tool_id
        return RegistrationResult(event, decision, entry.token)

    def approve(self, review_ref, *, approver, approved=True):
        try:
            approver = trusted_snapshot(approver)
            if type(approved) is not bool or type(review_ref) is not str:
                raise ValueError
            if "tool.approve" not in approver.permissions:
                raise ValueError
            with self._lock:
                tool_id = self._tokens.get(review_ref)
                entry = self._entries.get(tool_id)
                if (
                    entry is None
                    or entry.state != "REVIEW"
                    or time.monotonic() >= entry.expires
                    or approver.session_id != entry.event.session_id
                ):
                    raise ValueError
                entry.state = "APPROVING"
            decision = registration_decision(
                entry.event,
                "ALLOW" if approved else "BLOCK",
                "registry.approved" if approved else "registry.denied",
            )
            try:
                self._record(decision)
            except Exception:
                with self._lock:
                    if self._entries.get(tool_id) is entry:
                        entry.state = "BLOCK"
                        self._tokens.pop(review_ref, None)
                raise
            with self._lock:
                if (
                    self._entries.get(tool_id) is not entry
                    or entry.state != "APPROVING"
                    or time.monotonic() >= entry.expires
                ):
                    raise ValueError
                entry.state = decision.action.value
                self._tokens.pop(review_ref, None)
                entry.token = None
            return decision
        except Exception:
            raise ValueError("Registration approval rejected") from None

    def _resolve(self, call):
        entry = self._entries.get(call.tool_id)
        if entry is None:
            raise RegistryError("registry.unknown")
        if time.monotonic() >= entry.expires:
            if entry.token:
                self._tokens.pop(entry.token, None)
                entry.token = None
            if entry.state == "ALLOW":
                entry.state = "EXPIRED"
            raise RegistryError("registry.expired")
        if entry.state != "ALLOW":
            raise RegistryError("registry.denied")
        if entry.event.metadata_digest != call.metadata_digest or entry.event.name != call.name:
            raise RegistryError("registry.mismatch")
        return entry

    def binding_for(self, call):
        with self._lock:
            return self._resolve(call).binding

    def stamp(self, call):
        with self._lock:
            return self._resolve(call).generation

    @contextmanager
    def execution_guard(self, call, stamp):
        # Short admission lease covers final checks/reservation, never the tool body or plugins.
        with self._lock:
            entry = self._resolve(call)
            if entry.generation != stamp:
                raise RegistryError("registry.changed")
            yield entry.binding

    def bindings(self):
        with self._lock:
            return tuple(
                entry.binding
                for entry in self._entries.values()
                if entry.state == "ALLOW" and time.monotonic() < entry.expires
            )

    def revoke(self, tool_id, *, context):
        context = trusted_snapshot(context)
        if "tool.register" not in context.permissions:
            raise ValueError("Registry administration denied")
        with self._lock:
            entry = self._entries.get(tool_id)
            if entry is None:
                raise ValueError("Unknown tool")
            entry.state = "BLOCK"
            self._generation += 1
            entry.generation = self._generation
            if entry.token:
                self._tokens.pop(entry.token, None)
                entry.token = None
        self._record(registration_decision(entry.event, "BLOCK", "registry.revoked"))
