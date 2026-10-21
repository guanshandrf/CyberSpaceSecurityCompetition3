"""P2 wire contracts only: validation and correlation are not authorization or execution."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    PrivateAttr,
    StringConstraints,
    TypeAdapter,
    ValidationInfo,
    field_validator,
    model_validator,
)

Identifier = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    ),
]
Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
Source = Annotated[str, StringConstraints(min_length=1, max_length=256, pattern=r"^\S+$")]
GateId = Literal["gate0", "gate1", "gate2"]
MAX_WIRE_BYTES = 256 * 1024


def _as_tuple(value):
    return tuple(value) if type(value) is list else value


Identifiers = Annotated[tuple[Identifier, ...], BeforeValidator(_as_tuple)]


def _json_snapshot(value, *, limit):
    def walk(item, depth=0):
        if depth > 16:
            raise ValueError("JSON nesting exceeds 16 levels")
        if type(item) in (str, bool, int, type(None)):
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) is list:
            for child in item:
                walk(child, depth + 1)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for child in item.values():
                walk(child, depth + 1)
            return
        raise ValueError("Only finite native JSON values with string object keys are allowed")

    walk(value)
    encoded = json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > limit:
        raise ValueError("JSON payload exceeds its byte limit")
    return json.loads(encoded)  # Detach the contract from caller-owned mutable input.


class ContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        validate_default=True,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )


class SecurityEvent(ContractModel):
    schema_version: Literal["1.0"]
    event_id: Identifier
    event_type: Literal["tool_registration", "tool_call", "tool_result"]
    timestamp: AwareDatetime
    trace_id: Identifier
    session_id: Identifier

    @field_validator("timestamp", mode="before")
    @classmethod
    def parse_timestamp(cls, value):
        if type(value) is str:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError("timestamp must be ISO 8601 with timezone") from None
        return value

    @field_validator("timestamp")
    @classmethod
    def utc_timestamp(cls, value):
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def concrete_only(self):
        if type(self) is SecurityEvent:
            raise ValueError("Use one of the three concrete tool event models")
        return self


class ToolRegistrationEvent(SecurityEvent):
    event_type: Literal["tool_registration"]
    tool_id: Identifier
    name: Identifier
    metadata_digest: Digest
    version: Identifier | None = None
    source: Source
    description: str = Field(min_length=1, max_length=8192, repr=False)
    parameters_schema: dict[str, JsonValue] = Field(repr=False)
    capabilities: Identifiers
    permissions: Identifiers

    @field_validator("parameters_schema", mode="before")
    @classmethod
    def object_schema(cls, value):
        value = _json_snapshot(value, limit=16 * 1024)
        if type(value) is not dict or value.get("type") != "object":
            raise ValueError("Tool parameter schema must declare an object")
        if "properties" in value and type(value["properties"]) is not dict:
            raise ValueError("Schema properties must be an object")
        return value


class ToolCallEvent(SecurityEvent):
    event_type: Literal["tool_call"]
    tool_id: Identifier
    name: Identifier
    metadata_digest: Digest
    tool_call_id: Identifier
    arguments: dict[str, JsonValue] = Field(repr=False)
    source: Source
    context_ref: Identifier

    @field_validator("arguments", mode="before")
    @classmethod
    def json_arguments(cls, value):
        return _json_snapshot(value, limit=16 * 1024)


class ToolResultEvent(SecurityEvent):
    event_type: Literal["tool_result"]
    tool_id: Identifier
    name: Identifier
    metadata_digest: Digest
    tool_call_id: Identifier
    result_type: Literal["text", "json", "error"]
    content: JsonValue = Field(repr=False)
    source: Source
    is_error: bool
    truncated: bool = False
    original_size: int | None = Field(default=None, ge=0)
    evidence_ref: Identifier | None = None

    @field_validator("content", mode="before")
    @classmethod
    def json_content(cls, value):
        return _json_snapshot(value, limit=64 * 1024)

    @model_validator(mode="after")
    def result_shape(self):
        if self.result_type == "text" and type(self.content) is not str:
            raise ValueError("Text results require string content")
        if (self.result_type == "error") != self.is_error:
            raise ValueError("Error type and is_error must agree")
        retained = len(
            json.dumps(self.content, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        if self.truncated:
            if (
                self.original_size is None
                or self.original_size <= retained
                or self.evidence_ref is None
            ):
                raise ValueError("Truncation requires larger original_size and evidence_ref")
        elif self.original_size is not None and self.original_size != retained:
            raise ValueError("Non-truncated original_size must match retained JSON byte size")
        return self


class CallBudget(ContractModel):
    max_calls: int = Field(ge=1, le=1_000_000)
    calls_used: int = Field(ge=0)


_BACKEND_CAPABILITY = object()


class SecurityContext(ContractModel):
    """Only a trusted backend may call from_backend; this is not backend authentication."""

    schema_version: Literal["1.0"]
    context_id: Identifier
    user_id: Identifier = Field(repr=False)
    session_id: Identifier
    task_authorization: Identifier = Field(repr=False)
    allowed_resources: Identifiers = Field(repr=False)
    permissions: Identifiers = Field(repr=False)
    budget: CallBudget
    tool_provenance: Identifiers = ()
    risk_history: Identifiers = ()
    _backend_origin: object = PrivateAttr(default=None)

    @model_validator(mode="after")
    def backend_only(self, info: ValidationInfo):
        if (
            not isinstance(info.context, dict)
            or info.context.get("backend") is not _BACKEND_CAPABILITY
        ):
            raise ValueError("SecurityContext must be constructed by the trusted backend")
        self._backend_origin = _BACKEND_CAPABILITY
        return self

    @classmethod
    def from_backend(cls, **claims) -> SecurityContext:
        return cls.model_validate(claims, context={"backend": _BACKEND_CAPABILITY})

    def has_backend_provenance(self) -> bool:
        return self._backend_origin is _BACKEND_CAPABILITY

    def model_copy(self, *, update=None, deep=False):
        if update:
            raise TypeError("Context updates require a new trusted backend construction")
        copied = super().model_copy(deep=deep)
        if self.has_backend_provenance():
            copied._backend_origin = _BACKEND_CAPABILITY
        return copied


class Severity(StrEnum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SecurityFinding(ContractModel):
    code: Identifier
    severity: Severity
    evidence_ref: Identifier
    detector_id: Identifier

    @field_validator("severity", mode="before")
    @classmethod
    def severity_value(cls, value):
        return Severity(value) if type(value) is str else value


class DecisionAction(StrEnum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    REVIEW = "REVIEW"
    SANITIZE = "SANITIZE"


class SecurityDecision(ContractModel):
    schema_version: Literal["1.0"]
    gate: GateId
    event_id: Identifier
    trace_id: Identifier
    session_id: Identifier
    tool_id: Identifier
    tool_call_id: Identifier | None = None
    action: DecisionAction
    reason_codes: Identifiers = Field(min_length=1)
    findings: Annotated[tuple[SecurityFinding, ...], BeforeValidator(_as_tuple)] = ()
    matched_policies: Identifiers = ()
    replacement_content: JsonValue | None = Field(default=None, repr=False)

    @field_validator("action", mode="before")
    @classmethod
    def action_value(cls, value):
        return DecisionAction(value) if type(value) is str else value

    @field_validator("replacement_content", mode="before")
    @classmethod
    def replacement_json(cls, value):
        return _json_snapshot(value, limit=64 * 1024)

    @model_validator(mode="after")
    def gate_action(self):
        if self.gate == "gate0" and self.tool_call_id is not None:
            raise ValueError("Registration decisions cannot bind a tool call")
        if self.gate != "gate0" and self.tool_call_id is None:
            raise ValueError("Call/result decisions require tool_call_id")
        if self.action == DecisionAction.SANITIZE:
            if self.gate != "gate2" or self.replacement_content is None:
                raise ValueError(
                    "SANITIZE requires Gate 2 and explicit non-null replacement content"
                )
        elif self.replacement_content is not None:
            raise ValueError("Replacement content is only valid for SANITIZE")
        if self.gate == "gate2" and self.action == DecisionAction.REVIEW:
            raise ValueError("Gate 2 does not support REVIEW")
        return self


UnifiedEvent = Annotated[
    ToolRegistrationEvent | ToolCallEvent | ToolResultEvent,
    Field(discriminator="event_type"),
]
_EVENT_ADAPTER = TypeAdapter(UnifiedEvent, config=ConfigDict(hide_input_in_errors=True))


def parse_event(raw: str | bytes | dict | SecurityEvent):
    """Parse/revalidate exactly one wire event; never interpret content as trusted identity."""
    if isinstance(raw, SecurityEvent):
        # JSON serialization can silently turn NaN into null or bytes into text.
        # Revalidate original field values before any such conversion.
        raw = {name: getattr(raw, name) for name in type(raw).model_fields if hasattr(raw, name)}
    if isinstance(raw, str | bytes):
        size = len(raw.encode("utf-8")) if isinstance(raw, str) else len(raw)
        if size > MAX_WIRE_BYTES:
            raise ValueError("Event wire input exceeds 256 KiB")
        return _EVENT_ADAPTER.validate_json(raw)
    return _EVENT_ADAPTER.validate_python(raw)
