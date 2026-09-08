"""Stable, secret-safe expected error classification across user interfaces."""

from __future__ import annotations

from typing import Any

from agentic_data_platform.security.redaction import redact_string


def classify_expected_error(exc: Exception) -> str:
    if isinstance(exc, PermissionError):
        return "PERMISSION_FAILURE"
    if isinstance(exc, FileNotFoundError):
        return "USER_CONFIGURATION_ERROR"
    if isinstance(exc, KeyError):
        return "UNSUPPORTED_OR_NOT_FOUND"
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return "NETWORK_FAILURE"
    if isinstance(exc, ValueError):
        return "USER_CONFIGURATION_ERROR"
    return "INTERNAL_ERROR"


def safe_error(exc: Exception) -> dict[str, Any]:
    return {
        "error_type": classify_expected_error(exc),
        "message": redact_string(str(exc)),
    }
