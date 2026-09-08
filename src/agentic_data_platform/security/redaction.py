"""Central secret redaction for persisted/displayed execution evidence."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

_SENSITIVE_KEY = re.compile(r"(?:password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|oauth|authorization|cookie|private[_-]?key|credential)", re.I)
_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{12,}\b"),
    re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----"),
)
_ASSIGNMENT = re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token)\s*[:=]\s*([^\s,;]+)")


def redact_string(value: str) -> str:
    result = value
    for pattern in _PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    result = _ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", result)
    return result


def redact(value: Any, *, key: str | None = None) -> Any:
    if key and _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, str):
        return redact_string(value)
    if isinstance(value, Mapping):
        return {str(name): redact(item, key=str(name)) for name, item in value.items()}
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [redact(item) for item in value]
    return value
