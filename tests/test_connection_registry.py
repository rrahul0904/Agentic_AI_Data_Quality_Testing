from __future__ import annotations

import os

import pytest

from agentic_data_platform.connections import ConnectionStore, redact


def test_connection_store_requires_environment_references_for_secrets(tmp_path):
    store = ConnectionStore(tmp_path / "connections.db")
    with pytest.raises(ValueError):
        store.add("bad", "postgres", {"password": "plaintext"})

    item = store.add(
        "hotel",
        "postgres",
        {"host": "db.internal", "password": "${ENV:HOTEL_DB_PASSWORD}"},
    )
    assert item["config"]["host"] == "db.internal"
    assert item["config"]["password"] == "<redacted>"

    os.environ["HOTEL_DB_PASSWORD"] = "resolved-secret"
    resolved = store.resolve_config("hotel")
    assert resolved["config"]["password"] == "resolved-secret"
    assert "resolved-secret" not in str(store.show("hotel"))


def test_connection_default_remove_and_recursive_redaction(tmp_path):
    store = ConnectionStore(tmp_path / "connections.db")
    store.add("local", "sqlite", {"database": ":memory:"})
    store.set_default("local")
    assert store.show("local")["is_default"] is True
    assert store.default() == "local"
    assert store.remove("local") is True
    assert store.default() is None

    value = {"nested": {"api_token": "abc"}, "items": [{"password": "x"}]}
    assert redact(value) == {
        "nested": {"api_token": "<redacted>"},
        "items": [{"password": "<redacted>"}],
    }


def test_connection_discovery_from_environment_and_dbt_profiles(tmp_path, monkeypatch):
    monkeypatch.setenv("ADE_POSTGRES_DSN", "postgresql://example")
    profiles = tmp_path / "profiles.yml"
    profiles.write_text(
        """
hotel:
  target: dev
  outputs:
    dev:
      type: snowflake
      account: xy123
      user: analyst
      password: "{{ env_var('SNOWFLAKE_PASSWORD') }}"
"""
    )
    store = ConnectionStore(tmp_path / "connections.db")
    result = store.discover(dbt_profiles=profiles)
    assert result["environment"][0]["platform"] == "postgres"
    dbt = result["dbt_profiles"][0]
    assert dbt["platform"] == "snowflake"
    assert dbt["config"]["password"] == "<redacted>"
