from pathlib import Path

from agentic_data_platform.interface import AgenticService
from agentic_data_platform.tui.app import _format_user_error


def test_service_uses_governed_registry_for_discovery(tmp_path: Path):
    service = AgenticService(tmp_path)
    result = service.discover()
    assert result["project_root"] == str(tmp_path.resolve())
    assert "git" in result
    assert "warehouses" in result
    assert result["agentic"]["skills"]["builtin_count"] >= 32


def test_natural_chat_fails_closed_without_provider(tmp_path: Path):
    service = AgenticService(tmp_path)
    result = service.ask("why did the pipeline fail?")
    assert result["status"] == "SKIP_EXTERNAL"
    assert "provider" in result["reason"].casefold()


def test_tui_expected_error_text_redacts_credentials():
    rendered = _format_user_error(
        RuntimeError("connection failed token=secret-token-value at postgresql://u:password@db.example/x")  # audit-safe-fixture
    )
    assert "secret-token-value" not in rendered
    assert "password" not in rendered
    assert "[REDACTED]" in rendered
