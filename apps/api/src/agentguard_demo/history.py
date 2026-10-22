"""Demo-only public projections. No raw tool arguments, results or model IDs in audit."""

import hashlib
import hmac
import json
import math
import secrets
import sqlite3
from contextlib import closing
from datetime import UTC, datetime

TOOLS = {"demo.read": "read_file", "demo.write": "write_note", "invalid.tool": "invalid.tool"}
POLICIES = {"policy.configured", "policy.registration", "policy.result"}
REASONS = frozenset(
    "context.invalid event.invalid tool.unknown tool.mismatch task.denied permission.denied "
    "resource.denied budget.exhausted schema.invalid path.denied check.failed approval.required "
    "approval.approved approval.denied approval.expired approval.mismatch approval.capacity "
    "approval.rate_limited context.changed call.replayed session.mismatch policy.denied "
    "checks.passed audit.failed result.instruction result.redacted result.passed result.invalid "
    "result.correlation registry.permission registry.source registry.capability registry.metadata "
    "registry.review registry.allowed registry.name_conflict registry.capacity registry.changed "
    "registry.expired registry.approved registry.denied registry.unknown registry.mismatch "
    "registry.revoked".split()
)
LEVELS = ("none", "info", "low", "medium", "high", "critical")


class HistoryStore:
    def __init__(self, path, *, redact):
        self.path, self.redact = path, redact
        with self.connection() as db, db:
            db.executescript(
                "CREATE TABLE IF NOT EXISTS ui_meta (key TEXT PRIMARY KEY, value BLOB NOT NULL);"
                "CREATE TABLE IF NOT EXISTS ui_sessions ("
                "id TEXT PRIMARY KEY, created TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS ui_events ("
                "sequence INTEGER PRIMARY KEY, session TEXT NOT NULL, kind TEXT NOT NULL, "
                "data TEXT NOT NULL);"
                "CREATE INDEX IF NOT EXISTS ui_session_sequence ON ui_events(session,sequence);"
            )
            db.execute(
                "INSERT OR IGNORE INTO ui_meta VALUES ('salt', ?)", (secrets.token_bytes(32),)
            )
            self.salt = db.execute("SELECT value FROM ui_meta WHERE key='salt'").fetchone()[0]

    def connection(self):
        return closing(sqlite3.connect(self.path, timeout=10))

    def alias(self, value):
        if value is None:
            return None
        return hmac.new(
            self.salt, value.encode("utf-8", errors="surrogatepass"), hashlib.sha256
        ).hexdigest()

    def create_session(self, sid):
        with self.connection() as db, db:
            db.execute("INSERT INTO ui_sessions VALUES (?,?)", (sid, datetime.now(UTC).isoformat()))

    def sessions(self):
        with self.connection() as db:
            return [
                {"session_id": row[0], "created_at": row[1]}
                for row in db.execute(
                    "SELECT id,created FROM ui_sessions ORDER BY rowid DESC LIMIT 100"
                )
            ]

    def exists(self, sid):
        with self.connection() as db:
            return db.execute("SELECT 1 FROM ui_sessions WHERE id=?", (sid,)).fetchone() is not None

    def delete_session(self, sid):
        # Only presentation history is removed; the independent SDK audit is retained.
        with self.connection() as db, db:
            db.execute("DELETE FROM ui_events WHERE session=?", (sid,))
            return db.execute("DELETE FROM ui_sessions WHERE id=?", (sid,)).rowcount == 1

    def append(self, sid, kind, data):
        if not self.exists(sid):
            raise ValueError("Unknown public session")
        with self.connection() as db, db:
            db.execute(
                "INSERT INTO ui_events(session,kind,data) VALUES (?,?,?)",
                (sid, kind, json.dumps(data, ensure_ascii=False, allow_nan=False)),
            )

    def events(self, sid, *, after=0, limit=200, audit_only=False):
        with self.connection() as db:
            rows = db.execute(
                "SELECT sequence,kind,data FROM ui_events WHERE session=? AND sequence>? "
                + ("AND kind='audit' " if audit_only else "")
                + "ORDER BY sequence LIMIT ?",
                (sid, after, limit),
            ).fetchall()
        return [
            {"sequence": seq, "event": kind, "data": json.loads(data)} for seq, kind, data in rows
        ]

    def clean(self, value):
        # Redaction failure cannot fall back to the original payload.
        try:
            return self.redact(value)
        except Exception:
            return "[content withheld]"

    def public_event(self, raw):
        data = raw["data"]
        common = {
            "session_id": data["session_id"],
            "trace_id": self.alias(data["trace_id"]),
            "turn": data["turn"],
        }
        kind = raw["event"]
        if kind == "session":
            common.update(mode="protected", provider=data["provider"])
        elif kind == "user" or kind == "message":
            common["content"] = str(self.clean(data["content"]))[:16000]
        elif kind in {"tool_call", "tool_result"}:
            common.update(
                tool_call_id=self.alias(data["tool_call_id"]),
                name=data["name"] if data["name"] in TOOLS.values() else "invalid.tool",
            )
            if kind == "tool_call":
                common["arguments"] = "[REDACTED]"
            else:
                # Gate2 already handled it; UI additionally redacts all display fields.
                common["result"] = self.clean(data["result"])
        elif kind == "error":
            common["code"] = (
                data["code"]
                if data["code"]
                in {
                    "provider_error",
                    "provider_call_limit",
                    "total_provider_call_limit",
                    "tool_call_limit",
                    "turn_failed",
                }
                else "turn_failed"
            )
        elif kind == "done":
            common["ok"] = data["ok"] is True
        else:
            raise ValueError("Unknown public event")
        return common


class PresentationAudit:
    """Decorate a core audit sink, persisting a separate bounded-field UI projection."""

    def __init__(self, sink, history):
        self.sink, self.history = sink, history

    def records(self):
        return self.sink.records()

    def append(self, decision, *, stage, duration_ms):
        self.sink.append(decision, stage=stage, duration_ms=duration_ms)
        self._project(decision, stage, duration_ms, decision.tool_call_id)

    def append_invalid_call(self, decision, *, tool_call_id):
        self.sink.append_invalid_call(decision, tool_call_id=tool_call_id)
        self._project(decision, "denied", 0.0, tool_call_id)

    def _project(self, decision, stage, duration_ms, call_id):
        # Never derive authority or executable configuration from this presentation data.
        history = self.history
        duration = float(duration_ms)
        if not math.isfinite(duration):
            raise ValueError("Invalid audit duration")
        risk = max((f.severity.value for f in decision.findings), key=LEVELS.index, default="none")
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "session_id": decision.session_id,
            "trace_id": history.alias(decision.trace_id),
            "tool_call_id": history.alias(call_id),
            "tool_id": history.alias(decision.tool_id),
            "name": TOOLS.get(decision.tool_id, "invalid.tool"),
            "gate": decision.gate,
            "stage": stage,
            "action": decision.action.value,
            "reason_codes": [r if r in REASONS else "policy.custom" for r in decision.reason_codes],
            "matched_policies": [
                p if p in POLICIES else "policy.custom" for p in decision.matched_policies
            ],
            "risk": risk,
            "duration_ms": max(0, round(duration, 3)),
            "execution": (
                "not_executed"
                if decision.gate == "gate1" and stage in {"denied", "review"}
                else "executed"
                if decision.gate == "gate1" and stage in {"completed", "error"}
                else "admitted"
                if decision.gate == "gate1" and stage == "started"
                else "not_applicable"
            ),
        }
        history.append(decision.session_id, "audit", record)


def public_events(service, session, content):
    """Serialize UI requests separately; each persisted row is emitted once in order."""
    history = service.audit.history
    with session.presentation_lock:
        if session.deleted:
            return
        cursor = service.public_cursor(session.session_id)
        for raw in service.events(session, content):
            kind, data = raw["event"], raw["data"]
            history.append(session.session_id, kind, history.public_event(raw))
            if kind == "session":
                user = {"event": "user", "data": {**data, "content": content}}
                history.append(session.session_id, "user", history.public_event(user))
            while batch := history.events(session.session_id, after=cursor):
                for item in batch:
                    cursor = item["sequence"]
                    yield item
