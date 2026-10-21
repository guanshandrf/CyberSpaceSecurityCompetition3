"""Synchronous structural extension points; no default ALLOW or enforcement implementations."""

from typing import Protocol, runtime_checkable

from .models import GateId, SecurityContext, SecurityDecision, SecurityFinding, UnifiedEvent


@runtime_checkable
class Detector(Protocol):
    detector_id: str

    def detect(
        self, event: UnifiedEvent, context: SecurityContext
    ) -> tuple[SecurityFinding, ...]: ...


@runtime_checkable
class Policy(Protocol):
    policy_id: str

    def evaluate(
        self,
        event: UnifiedEvent,
        context: SecurityContext,
        findings: tuple[SecurityFinding, ...],
    ) -> SecurityDecision: ...


@runtime_checkable
class Gate(Protocol):
    gate_id: GateId

    def evaluate(self, event: UnifiedEvent, context: SecurityContext) -> SecurityDecision: ...
