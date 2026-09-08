from __future__ import annotations

from agentic_data_platform.errors import classify_expected_error, safe_error


def test_error_model_distinguishes_expected_categories():
    assert classify_expected_error(ValueError("bad config")) == "USER_CONFIGURATION_ERROR"
    assert classify_expected_error(FileNotFoundError("missing")) == "USER_CONFIGURATION_ERROR"
    assert classify_expected_error(KeyError("unsupported")) == "UNSUPPORTED_OR_NOT_FOUND"
    assert classify_expected_error(PermissionError("denied")) == "PERMISSION_FAILURE"
    assert classify_expected_error(TimeoutError("slow")) == "NETWORK_FAILURE"
    assert classify_expected_error(RuntimeError("bug")) == "INTERNAL_ERROR"


def test_error_model_redacts_secret_bearing_messages():
    error = safe_error(
        ValueError("token=super-secret-token postgresql://alice:password@db.example/warehouse")
    )
    assert error["error_type"] == "USER_CONFIGURATION_ERROR"
    assert "super-secret-token" not in error["message"]
    assert "password@" not in error["message"]
    assert "[REDACTED]" in error["message"]
