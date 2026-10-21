"""Content redaction is separate from the audit field allowlist."""

import json
import re

from agentguard.contracts.models import _json_snapshot

_SECRET_FIELD = re.compile(
    r"^(?:api[_ -]?key|access[_ -]?token|password|secret|authorization)$", re.I
)
_PATTERNS = (
    re.compile(
        r"-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"
    ),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b(?:ghp_|github_pat_)[A-Za-z0-9_]{16,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.I),
    re.compile(
        r"\b(?:api[_ -]?key|access[_ -]?token|password|secret)\s*[:=]\s*[\"']?[^\s,;\"']{4,}", re.I
    ),
)


class Redactor:
    def __init__(self, *, secrets=()):
        values = tuple(secrets)
        if any(type(value) is not str or not value for value in values):
            raise ValueError("Redaction secrets must be nonempty strings")
        self._secrets = tuple(sorted(values, key=len, reverse=True))

    def _text(self, text):
        for secret in self._secrets:
            text = text.replace(secret, "[REDACTED]")
        for pattern in _PATTERNS:
            text = pattern.sub("[REDACTED]", text)
        return text

    def redact(self, value):
        if type(value) is str:
            if value.lstrip().startswith(("{", "[")):
                try:
                    decoded = json.loads(value)
                except json.JSONDecodeError:
                    pass
                else:
                    decoded = _json_snapshot(decoded, limit=64 * 1024)
                    clean = self.redact(decoded)
                    if clean != decoded:
                        return json.dumps(clean, ensure_ascii=False)
            return self._text(value)
        if type(value) is list:
            return [self.redact(item) for item in value]
        if type(value) is dict:
            result = {}
            for key, item in value.items():
                clean_key = self._text(key)
                if clean_key in result:
                    raise ValueError("Redacted key collision")
                result[clean_key] = (
                    "[REDACTED]" if _SECRET_FIELD.fullmatch(key) else self.redact(item)
                )
            return result
        return value
