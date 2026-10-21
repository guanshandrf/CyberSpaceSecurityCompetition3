"""Allowlist audit: never persist arguments, paths, output, approval tokens or errors."""

import hashlib
import hmac
import json
import secrets
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

SAFE_REASONS = frozenset(
    {
        "context.invalid",
        "event.invalid",
        "tool.unknown",
        "tool.mismatch",
        "task.denied",
        "permission.denied",
        "resource.denied",
        "budget.exhausted",
        "schema.invalid",
        "path.denied",
        "check.failed",
        "approval.required",
        "approval.approved",
        "approval.denied",
        "approval.expired",
        "approval.mismatch",
        "approval.capacity",
        "approval.rate_limited",
        "context.changed",
        "call.replayed",
        "session.mismatch",
        "policy.denied",
        "checks.passed",
        "audit.failed",
        "result.instruction",
        "result.redacted",
        "result.passed",
        "result.invalid",
        "result.correlation",
        "registry.permission",
        "registry.source",
        "registry.capability",
        "registry.metadata",
        "registry.review",
        "registry.allowed",
        "registry.name_conflict",
        "registry.capacity",
        "registry.changed",
        "registry.expired",
        "registry.approved",
        "registry.denied",
        "registry.unknown",
        "registry.mismatch",
        "registry.revoked",
    }
)


class SQLiteAudit:
    """One connection per append supports threads; HMAC identifiers link this sink's run."""

    def __init__(self, path: Path):
        self._path = Path(path)
        self._salt = secrets.token_bytes(32)
        with closing(sqlite3.connect(self._path)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS audit "
                "(sequence INTEGER PRIMARY KEY, record TEXT NOT NULL)"
            )

    def append(self, decision, *, stage, duration_ms):
        self._append(decision, stage=stage, duration_ms=duration_ms)

    def append_invalid_call(self, decision, *, tool_call_id):
        """Malformed IDs cannot enter P2 contracts; retain their HMAC, never arguments."""
        if (
            decision.gate != "gate1"
            or decision.action != "BLOCK"
            or decision.reason_codes != ("event.invalid",)
        ):
            raise ValueError("Invalid adapter rejection")
        self._append(decision, stage="denied", duration_ms=0.0, original_call_id=tool_call_id)

    def _append(self, decision, *, stage, duration_ms, original_call_id=None):
        if stage not in {
            "denied",
            "review",
            "approved",
            "rejected",
            "started",
            "completed",
            "error",
            "handled",
            "registered",
        }:
            raise ValueError("Invalid audit stage")

        def digest(value):
            return hmac.new(
                self._salt, value.encode("utf-8", errors="surrogatepass"), hashlib.sha256
            ).hexdigest()

        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "gate": decision.gate,
            "stage": stage,
            "action": decision.action.value,
            "reason_codes": [
                r if r in SAFE_REASONS else "policy.custom" for r in decision.reason_codes
            ],
            "duration_ms": max(0, round(float(duration_ms), 3)),
            **{
                key: digest(getattr(decision, key) or "")
                for key in ("event_id", "trace_id", "session_id", "tool_id", "tool_call_id")
            },
        }
        if type(original_call_id) is str:
            record["tool_call_id"] = digest(original_call_id)
        with closing(sqlite3.connect(self._path)) as connection, connection:
            connection.execute("INSERT INTO audit(record) VALUES (?)", (json.dumps(record),))

    def records(self):
        with closing(sqlite3.connect(self._path)) as connection:
            return [
                json.loads(row[0])
                for row in connection.execute("SELECT record FROM audit ORDER BY sequence")
            ]
