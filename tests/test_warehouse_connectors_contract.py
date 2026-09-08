from __future__ import annotations

import sqlite3

import pytest

from agentic_data_platform.connectors import (
    ClickHouseConnector,
    MySQLConnector,
    OracleConnector,
    PostgreSQLConnector,
    RedshiftConnector,
    SQLServerConnector,
    SQLiteConnector,
    TrinoConnector,
)
from agentic_data_platform.connectors.capabilities import ConnectorCapability
from agentic_data_platform.connectors.factory import ExternalConnectionUnavailable, connector_from_args


class InformationSchemaFixture:
    def __call__(self, sql: str):
        lowered = sql.lower()
        if "pg_database" in lowered:
            return {"columns": ("catalog",), "rows": ({"catalog": "demo"},)}
        if "information_schema.schemata" in lowered:
            return {
                "columns": ("catalog", "schema"),
                "rows": ({"catalog": "demo", "schema": "public"},),
            }
        if "information_schema.tables" in lowered:
            return {
                "columns": ("catalog", "name", "object_type"),
                "rows": ({"catalog": "demo", "name": "orders", "object_type": "BASE TABLE"},),
            }
        if "information_schema.columns" in lowered:
            return {
                "columns": (
                    "catalog",
                    "name",
                    "data_type",
                    "is_nullable",
                    "ordinal_position",
                    "numeric_precision",
                    "numeric_scale",
                    "column_default",
                ),
                "rows": (
                    {
                        "catalog": "demo",
                        "name": "id",
                        "data_type": "integer",
                        "is_nullable": "NO",
                        "ordinal_position": 1,
                        "numeric_precision": 32,
                        "numeric_scale": 0,
                        "column_default": None,
                    },
                ),
            }
        if "pg_stat_statements" in lowered:
            return {
                "columns": ("queryid", "calls", "total_exec_time", "mean_exec_time", "rows", "query"),
                "rows": (
                    {
                        "queryid": 1,
                        "calls": 3,
                        "total_exec_time": 12.0,
                        "mean_exec_time": 4.0,
                        "rows": 30,
                        "query": "SELECT * FROM orders",
                    },
                ),
            }
        if "stl_query" in lowered:
            return {
                "columns": ("query", "userid", "starttime", "endtime", "aborted", "querytxt"),
                "rows": (
                    {
                        "query": 11,
                        "userid": 1,
                        "starttime": "2026-01-01",
                        "endtime": "2026-01-01",
                        "aborted": 0,
                        "querytxt": "SELECT 1",
                    },
                ),
            }
        if lowered.startswith("explain"):
            return {"columns": ("plan",), "rows": ({"plan": "fixture plan"},)}
        if lowered.startswith("select"):
            return {"columns": ("id",), "rows": ({"id": 1},)}
        return {"columns": (), "rows": ()}


class OracleFixture:
    def __call__(self, sql: str):
        lowered = sql.lower()
        if "from all_users" in lowered:
            return {"columns": ("schema_name",), "rows": ({"schema_name": "HOTEL"},)}
        if "from all_tables" in lowered:
            return {
                "columns": ("schema_name", "name", "object_type"),
                "rows": ({"schema_name": "HOTEL", "name": "RESERVATION", "object_type": "TABLE"},),
            }
        if "from all_tab_columns" in lowered:
            return {
                "columns": ("name", "data_type", "nullable", "ordinal_position", "numeric_precision", "numeric_scale", "column_default"),
                "rows": (
                    {
                        "name": "RESERVATION_ID",
                        "data_type": "NUMBER",
                        "nullable": "N",
                        "ordinal_position": 1,
                        "numeric_precision": 38,
                        "numeric_scale": 0,
                        "column_default": None,
                    },
                ),
            }
        if "dbms_metadata.get_ddl" in lowered:
            return {"columns": ("ddl",), "rows": ({"ddl": "CREATE TABLE HOTEL.RESERVATION (...)"},)}
        if "dbms_xplan" in lowered:
            return {"columns": ("plan",), "rows": ({"plan": "TABLE ACCESS"},)}
        return {"columns": (), "rows": ()}


class ClickHouseFixture:
    def __call__(self, sql: str):
        lowered = sql.lower()
        if "system.databases" in lowered:
            return {"columns": ("name",), "rows": ({"name": "hotel"},)}
        if "system.tables" in lowered and "create_table_query" in lowered:
            return {"columns": ("ddl",), "rows": ({"ddl": "CREATE TABLE hotel.orders (id UInt64)"},)}
        if "system.tables" in lowered:
            return {
                "columns": ("database", "name", "engine"),
                "rows": ({"database": "hotel", "name": "orders", "engine": "MergeTree"},),
            }
        if "system.columns" in lowered:
            return {
                "columns": ("database", "table", "name", "type", "position", "default_expression"),
                "rows": ({"database": "hotel", "table": "orders", "name": "id", "type": "UInt64", "position": 1, "default_expression": ""},),
            }
        if "system.query_log" in lowered:
            return {
                "columns": ("query_id", "user", "query_duration_ms", "read_rows", "read_bytes", "result_rows", "query"),
                "rows": ({"query_id": "q1", "user": "default", "query_duration_ms": 10, "read_rows": 1, "read_bytes": 8, "result_rows": 1, "query": "SELECT 1"},),
            }
        if lowered.startswith("explain"):
            return {"columns": ("plan",), "rows": ({"plan": "Expression"},)}
        return {"columns": ("id",), "rows": ({"id": 1},)}


class TrinoFixture:
    def __call__(self, sql: str):
        lowered = sql.lower()
        if lowered == "show catalogs":
            return {"columns": ("catalog",), "rows": ({"catalog": "hive"}, {"catalog": "iceberg"})}
        if lowered.startswith("show schemas"):
            return {"columns": ("schema",), "rows": ({"schema": "hotel"},)}
        if lowered.startswith("show tables"):
            return {"columns": ("table",), "rows": ({"table": "orders"},)}
        if lowered.startswith("describe"):
            return {"columns": ("column", "type"), "rows": ({"column": "id", "type": "bigint"},)}
        if lowered.startswith("explain"):
            return {"columns": ("plan",), "rows": ({"plan": "Output"},)}
        return {"columns": ("id",), "rows": ({"id": 1},)}


@pytest.mark.parametrize("connector_cls", [PostgreSQLConnector, RedshiftConnector, MySQLConnector, SQLServerConnector])
def test_information_schema_connectors_have_real_read_metadata_contract(connector_cls):
    connector = connector_cls(InformationSchemaFixture())
    assert ConnectorCapability.QUERY_READ in connector.capabilities()
    assert ConnectorCapability.GET_DDL in connector.capabilities()
    if connector.platform not in {"mysql", "sqlserver"}:
        assert connector.list_catalogs()
    assert connector.list_schemas()
    assert connector.list_tables("public")[0].name == "orders"
    table = connector.describe_table("public", "orders")
    assert table.columns[0].name == "id"
    assert table.columns[0].nullable is False
    assert "CREATE TABLE public.orders" in connector.get_ddl("public", "orders")
    assert connector.execute_read("SELECT 1").rows == ({"id": 1},)
    assert connector.dry_run_sql("SELECT 1").valid is True


def test_postgres_and_redshift_query_history_are_explicit():
    assert PostgreSQLConnector(InformationSchemaFixture()).query_history()[0]["queryid"] == 1
    assert RedshiftConnector(InformationSchemaFixture()).query_history()[0]["query"] == 11


def test_oracle_metadata_ddl_and_explain_contract():
    connector = OracleConnector(OracleFixture())
    assert connector.list_schemas()[0].name == "HOTEL"
    assert connector.list_tables("HOTEL")[0].name == "RESERVATION"
    assert connector.describe_table("HOTEL", "RESERVATION").columns[0].data_type == "NUMBER"
    assert connector.get_ddl("HOTEL", "RESERVATION").startswith("CREATE TABLE")
    assert connector.dry_run_sql("SELECT 1 FROM dual").valid is True


def test_clickhouse_contract_and_history():
    connector = ClickHouseConnector(ClickHouseFixture())
    assert connector.list_catalogs() == ["hotel"]
    assert connector.list_tables("hotel")[0].object_type == "MergeTree"
    assert connector.describe_table("hotel", "orders").columns[0].data_type == "UInt64"
    assert connector.query_history()[0]["query_id"] == "q1"
    assert connector.dry_run_sql("SELECT 1").valid is True


def test_trino_contract():
    connector = TrinoConnector(TrinoFixture(), catalog="hive")
    assert "hive" in connector.list_catalogs()
    assert connector.list_schemas()[0].name == "hotel"
    assert connector.list_tables("hotel")[0].name == "orders"
    assert connector.describe_table("hotel", "orders").columns[0].data_type == "bigint"
    assert connector.dry_run_sql("SELECT 1").valid is True


def test_sqlite_real_contract():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE orders(id INTEGER NOT NULL, amount REAL)")
    connector = SQLiteConnector(connection)
    assert "main" in connector.list_catalogs()
    assert connector.list_tables("main")[0].name == "orders"
    metadata = connector.describe_table("main", "orders")
    assert [column.name for column in metadata.columns] == ["id", "amount"]
    assert "CREATE TABLE orders" in connector.get_ddl("main", "orders")
    assert connector.dry_run_sql("SELECT * FROM orders").valid is True


def test_factory_fails_closed_when_credentials_are_missing(monkeypatch):
    for name in (
        "ADE_POSTGRES_DSN",
        "ADE_REDSHIFT_DSN",
        "ADE_MYSQL_HOST",
        "ADE_MYSQL_USER",
        "ADE_MYSQL_PASSWORD",
        "ADE_MYSQL_DATABASE",
        "ADE_SQLSERVER_CONNECTION_STRING",
        "ADE_ORACLE_USER",
        "ADE_ORACLE_PASSWORD",
        "ADE_ORACLE_DSN",
        "ADE_CLICKHOUSE_HOST",
        "ADE_TRINO_HOST",
        "ADE_TRINO_USER",
        "ADE_TRINO_CATALOG",
        "ADE_MONGODB_URI",
    ):
        monkeypatch.delenv(name, raising=False)

    for platform in ("postgres", "redshift", "mysql", "sqlserver", "oracle", "clickhouse", "trino", "mongodb"):
        with pytest.raises(ExternalConnectionUnavailable):
            connector_from_args({"platform": platform})

class MongoCollectionFixture:
    def __init__(self):
        self.rows = [{"_id": 1, "guest_id": 7, "email": "fixture@example.test"}]

    def find(self, filter_doc, projection=None, limit=100):
        return list(self.rows)[:limit]

    def aggregate(self, pipeline):
        return list(self.rows)


class MongoDatabaseFixture:
    def __init__(self):
        self.collection = MongoCollectionFixture()

    def list_collection_names(self):
        return ["reservations"]

    def __getitem__(self, name):
        assert name == "reservations"
        return self.collection


class MongoClientFixture:
    def list_database_names(self):
        return ["hotel"]

    def __getitem__(self, name):
        assert name == "hotel"
        return MongoDatabaseFixture()


def test_mongodb_read_only_metadata_and_json_query_contract():
    from agentic_data_platform.connectors import MongoDBConnector

    connector = MongoDBConnector(MongoClientFixture(), database="hotel")
    assert connector.list_catalogs() == ["hotel"]
    assert connector.list_tables("hotel")[0].name == "reservations"
    metadata = connector.describe_table("hotel", "reservations")
    assert {column.name for column in metadata.columns} >= {"_id", "guest_id", "email"}
    query = '{"collection":"reservations","filter":{"guest_id":7},"limit":10}'
    assert connector.dry_run_sql(query).valid is True
    result = connector.execute_read(query)
    assert result.rows[0]["guest_id"] == 7
    blocked = '{"collection":"reservations","operation":"aggregate","pipeline":[{"$out":"copy"}]}'
    assert connector.dry_run_sql(blocked).valid is False


def test_common_warehouse_adapter_metadata_and_permissions_contract():
    from agentic_data_platform.connectors.warehouse import ConnectorWarehouseAdapter
    from agentic_data_platform.connectors.sqlite import SQLiteConnector

    adapter = ConnectorWarehouseAdapter(SQLiteConnector(":memory:"))
    metadata = adapter.metadata()
    assert metadata["status"] == "PASS"
    assert metadata["platform"] == "sqlite"
    permissions = adapter.permissions()
    assert permissions["status"] in {"PASS", "SKIP_EXTERNAL"}
    assert "platform" in permissions
