from __future__ import annotations

from agentic_data_platform.connections.dbt_profiles import discover_dbt_profiles
from agentic_data_platform.tools.builtin import build_tool_registry
from agentic_data_platform.tools.parity_utils import (
    PostConnectSuggestions,
    normalize_error,
    validate_table_name,
    validate_warehouse_name,
)


def test_input_validation_matches_preflight_contract():
    assert validate_warehouse_name(None) is None
    assert validate_warehouse_name("") is not None
    assert validate_warehouse_name("$WAREHOUSE") is not None
    assert validate_warehouse_name("analytics") is None
    assert validate_table_name(None) is not None
    assert validate_table_name(":table") is not None
    assert validate_table_name("analytics.orders") is None


def test_response_normalization_never_stringifies_unknown_error_objects():
    assert normalize_error(None) is None
    assert normalize_error(False) is None
    assert normalize_error({"message": "safe"}) == "safe"
    assert normalize_error({"secret": "do-not-leak"}) == "Error details unavailable."
    assert normalize_error(ValueError("bad input")) == "bad input"


def test_post_connect_suggestions_and_progressive_dedupe():
    service = PostConnectSuggestions()
    suggestions = service.post_connect(
        warehouse_type="snowflake",
        schema_indexed=False,
        dbt_detected=True,
        connection_count=2,
    )
    joined = " ".join(suggestions)
    assert "schema_index" in joined
    assert "sql_execute" in joined
    assert "dbt" in joined
    assert "data_diff" in joined

    first = service.progressive("sql_execute")
    second = service.progressive("sql_execute")
    assert first
    assert second is None
    service.reset()
    assert service.progressive("sql_execute") == first


def test_dbt_profiles_discovery_redacts_credentials(tmp_path):
    profiles = tmp_path / "profiles.yml"
    profiles.write_text(
        "hotel:\n"
        "  target: prod\n"
        "  outputs:\n"
        "    prod:\n"
        "      type: snowflake\n"
        "      account: acct\n"
        "      user: analyst\n"
        "      password: secret-value\n"
        "      private_key: very-secret\n"
    )
    result = discover_dbt_profiles(path=profiles)
    assert result["connection_count"] == 1
    config = result["connections"][0]["config"]
    assert config["account"] == "acct"
    assert config["password"] == "****"
    assert config["private_key"] == "****"
    assert "secret-value" not in str(result)


def test_tool_lookup_exposes_contract_without_execution():
    registry = build_tool_registry()
    definition = registry.describe("tool_lookup")
    result = definition.handler(
        {"tool_name": "sql_classify", "_run_id": "test", "_dry_run": False}
    )
    assert result["status"] == "PASS"
    assert result["tool"]["name"] == "sql_classify"
    assert result["tool"]["risk"] == "read_only"

    missing = definition.handler(
        {"tool_name": "not-real", "_run_id": "test", "_dry_run": False}
    )
    assert missing["status"] == "NOT_FOUND"
    assert "sql_classify" in missing["available_tools"]
