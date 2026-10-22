"""Explicitly enabled bounded API attempts, with a persistent shared authorization ledger."""

import json
import os
import sqlite3
import urllib.error
import urllib.request
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from agentguard.detectors import Redactor
from agentguard.policies import PathRule

AUTHORIZATION = "P8-20261021-20-attempts-256-output-tokens"
MAX_ATTEMPTS = 20
MAX_OUTPUT_TOKENS = 256
MAX_INPUT_BYTES = 32000


class BudgetExhausted(RuntimeError):
    pass


class LiveFailure(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward API credentials to a redirected origin.
        return None


class LiveBudget:
    """Failed requests consume attempts; restart and concurrency cannot reset this ledger."""

    def __init__(self, directory: Path):
        directory = Path(directory)
        if not directory.is_dir():
            raise ValueError("Create a repository-local budget directory first")
        self.path = Path(
            PathRule("ledger", "budget", directory, must_exist=False).resolve_argument(
                "budget.sqlite"
            )
        )
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY, "
                "authorization TEXT NOT NULL, metadata TEXT NOT NULL)"
            )

    def reserve(self):
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            used = db.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
            if used >= MAX_ATTEMPTS:
                raise BudgetExhausted("Authorized API attempts exhausted")
            metadata = {"started_at": datetime.now(UTC).isoformat(), "status": "reserved"}
            return db.execute(
                "INSERT INTO requests(authorization,metadata) VALUES (?,?)",
                (AUTHORIZATION, json.dumps(metadata)),
            ).lastrowid

    def finish(self, request_id, *, status, usage=None, http_status=None):
        if status not in {"completed", "request_failed", "invalid_response"}:
            raise ValueError("Invalid API request status")
        usage = usage or {}
        safe_usage = {
            k: usage[k]
            for k in ("prompt_tokens", "completion_tokens", "total_tokens")
            if type(usage.get(k)) is int and usage[k] >= 0
        }
        metadata = {
            "finished_at": datetime.now(UTC).isoformat(),
            "status": status,
            "usage": safe_usage,
            "cost": None,
            "cost_reason": "No verified price snapshot",
        }
        if type(http_status) is int and 300 <= http_status <= 599:
            metadata["http_status"] = http_status
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute(
                "UPDATE requests SET metadata=? WHERE id=?", (json.dumps(metadata), request_id)
            )

    def records(self):
        with closing(sqlite3.connect(self.path)) as db:
            return [
                {"attempt": row[0], **json.loads(row[1])}
                for row in db.execute("SELECT id,metadata FROM requests ORDER BY id")
            ]


def local_key(root):
    """Read only the explicitly named local config; never search parents or echo values."""
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        path = PathRule("config", "config", root, must_exist=False).resolve_argument(".env")
        if Path(path).is_file():
            from dotenv import dotenv_values

            key = dotenv_values(path, interpolate=False).get("DEEPSEEK_API_KEY", "") or ""
    if not key:
        raise LiveFailure("Missing local DeepSeek credential")
    return key


class DeepSeek:
    provider_id = "deepseek-chat-real"

    def __init__(self, *, root, budget, enabled=False, max_output_tokens=MAX_OUTPUT_TOKENS):
        if enabled is not True:
            raise LiveFailure("Real API requires explicit enablement")
        if type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 512:
            raise LiveFailure("Output token limit must be 1..512")
        if max_output_tokens > getattr(budget, "max_output_tokens", MAX_OUTPUT_TOKENS):
            raise LiveFailure("Output token limit exceeds this authorization")
        self.max_output_tokens = max_output_tokens
        self._key = local_key(root)
        self.redactor = Redactor(secrets=(self._key,))
        self._open = urllib.request.build_opener(NoRedirect()).open
        self.budget = budget
        self.last_usage = None
        self.response_metadata = {}

    def redact(self, value):
        return self.redactor.redact(value)

    def complete(self, messages, *, tools=()):
        body = {
            "model": "deepseek-chat",
            "messages": messages,
            "temperature": 0,
            "max_tokens": self.max_output_tokens,
            "stream": False,
        }
        if tools:
            body["tools"] = list(tools)
        encoded = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_INPUT_BYTES:
            raise LiveFailure("API input exceeds configured byte limit")
        request = urllib.request.Request(
            "https://api.deepseek.com/chat/completions",
            data=encoded,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + self._key},
            method="POST",
        )
        request_id = self.budget.reserve()
        try:
            # Uses the existing system HTTPS proxy without changing any configuration.
            with self._open(request, timeout=30) as response:
                raw = response.read(512 * 1024 + 1)
            if len(raw) > 512 * 1024:
                raise ValueError("Oversized provider response")
        except urllib.error.HTTPError as exc:
            self.budget.finish(request_id, status="request_failed", http_status=exc.code)
            raise LiveFailure("DeepSeek HTTP request failed; attempt consumed") from None
        except Exception:
            self.budget.finish(request_id, status="request_failed")
            raise LiveFailure("DeepSeek request failed; attempt consumed") from None
        try:
            result = json.loads(raw)
            message = result["choices"][0]["message"]
            if type(message) is not dict or message.get("role") != "assistant":
                raise ValueError
            usage = result.get("usage", {})
            self.response_metadata = {
                "model": result.get("model"),
                "system_fingerprint": result.get("system_fingerprint"),
                "finish_reason": result["choices"][0].get("finish_reason"),
            }
            self.last_usage = usage
            self.budget.finish(request_id, status="completed", usage=usage)
            return message
        except Exception:
            self.budget.finish(request_id, status="invalid_response")
            raise LiveFailure("Invalid DeepSeek response; attempt consumed") from None
