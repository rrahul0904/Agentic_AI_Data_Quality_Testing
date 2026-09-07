from __future__ import annotations

import sqlite3

from agentic_data_platform.connectors.sqlite import SQLiteConnector
from agentic_data_platform.metadata.service import MetadataService


def test_metadata_refresh_search_inspect_and_schema_context(tmp_path):
    source = sqlite3.connect(":memory:")
    source.execute("CREATE TABLE reservations(reservation_id INTEGER NOT NULL, guest_email TEXT, amount REAL)")
    source.execute("CREATE VIEW reservation_ids AS SELECT reservation_id FROM reservations")
    connector = SQLiteConnector(source)

    service = MetadataService(tmp_path / "metadata.db")
    result = service.refresh("local", connector, schemas=["main"])
    assert result["status"] == "PASS"
    assert result["objects"] == 2
    assert result["columns"] >= 4

    assets = service.search_assets("reservation", connection_name="local")
    assert {item["object_name"] for item in assets} == {"reservation_ids", "reservations"}

    columns = service.search_columns("email", connection_name="local")
    assert columns[0]["column_name"] == "guest_email"

    detail = service.inspect("local", "main", "reservations")
    assert [column["column_name"] for column in detail["columns"]] == [
        "reservation_id",
        "guest_email",
        "amount",
    ]

    context = service.schema_context(connection_name="local", query="reservation")
    assert context["reservations"]["reservation_id"].upper().startswith("INTEGER")


def test_metadata_pii_state_is_persistent(tmp_path):
    source = sqlite3.connect(":memory:")
    source.execute("CREATE TABLE guests(id INTEGER, email TEXT)")
    service = MetadataService(tmp_path / "metadata.db")
    service.refresh("local", SQLiteConnector(source), schemas=["main"])
    column = service.search_columns("email")[0]
    service.set_pii(column["object_id"], "email", "email", 0.98)
    pii = service.search_columns("", pii_only=True)
    assert pii[0]["pii_category"] == "email"
    assert pii[0]["pii_confidence"] == 0.98


def test_metadata_refresh_fails_closed_on_object_bound(tmp_path):
    source = sqlite3.connect(":memory:")
    source.execute("CREATE TABLE a(id INTEGER)")
    source.execute("CREATE TABLE b(id INTEGER)")
    service = MetadataService(tmp_path / "metadata.db")
    try:
        service.refresh("local", SQLiteConnector(source), schemas=["main"], max_objects=1)
    except RuntimeError as exc:
        assert "max_objects" in str(exc)
    else:
        raise AssertionError("expected bounded refresh failure")
    assert service.status("local")["last_refresh"]["status"] == "FAILED"
