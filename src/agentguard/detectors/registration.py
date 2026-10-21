"""Descriptions remain low-trust data after metadata admission."""

from agentguard.contracts import SecurityFinding, ToolRegistrationEvent

from .results import has_instructions


class RegistrationDetector:
    detector_id = "detector.registration.rules"

    def detect(self, event, context):
        if type(event) is not ToolRegistrationEvent:
            raise ValueError("Registration event required")
        if has_instructions(event.description):
            return (
                SecurityFinding(
                    code="tool.description",
                    severity="high",
                    evidence_ref=event.event_id,
                    detector_id=self.detector_id,
                ),
            )
        return ()
