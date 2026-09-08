from __future__ import annotations

import sqlite3

import duckdb

from agentic_data_platform.connectors.duckdb import DuckDBConnector
from agentic_data_platform.connectors.sqlite import SQLiteConnector
from agentic_data_platform.quality.warehouse_diff import (
    WarehouseDiffEngine,
    hash_diff,
    join_diff,
    profile_diff,
)


def _duckdb_fixture():
    connection = duckdb.connect(":memory:")
    connection.execute("CREATE SCHEMA src")
    connection.execute("CREATE SCHEMA tgt")
    connection.execute("CREATE TABLE src.orders(id INTEGER, amount DOUBLE, status VARCHAR)")
    connection.execute("CREATE TABLE tgt.orders(id INTEGER, amount DOUBLE, status VARCHAR)")
    connection.execute(
        "INSERT INTO src.orders VALUES "
        "(1, 10.0, 'OK'), (2, 20.0, 'OK'), (3, 30.0, 'CANCELLED'), (4, 40.0, 'OK')"
    )
    connection.execute(
        "INSERT INTO tgt.orders VALUES "
        "(1, 10.0, 'OK'), (2, 25.0, 'OK'), (4, 40.0, 'OK'), (5, 50.0, 'OK')"
    )
    return connection


def test_profile_diff_pushes_aggregates_and_returns_no_raw_rows():
    connector = DuckDBConnector(_duckdb_fixture())
    result = profile_diff(
        connector,
        connector,
        "src.orders",
        "tgt.orders",
        columns=["id", "amount"],
    )
    assert result["algorithm"] == "PROFILE"
    assert result["status"] == "FAIL"
    assert result["source"]["raw_rows_retrieved"] == 0
    assert result["target"]["raw_rows_retrieved"] == 0
    assert any(item.get("column") == "amount" for item in result["differences"])


def test_join_diff_uses_full_outer_pushdown_on_same_connector():
    connector = DuckDBConnector(_duckdb_fixture())
    result = join_diff(
        connector,
        connector,
        "src.orders",
        "tgt.orders",
        key_columns=["id"],
        compare_columns=["amount", "status"],
    )
    assert result["execution"] == "WAREHOUSE_PUSHDOWN"
    assert result["status"] == "FAIL"
    assert result["counts"]["changed"] == 1
    assert result["counts"]["missing"] == 1
    assert result["counts"]["extra"] == 1


def test_hash_diff_is_partition_bounded_and_moves_hashes_not_raw_rows():
    connection = _duckdb_fixture()
    source = DuckDBConnector(connection)
    target = DuckDBConnector(connection)
    result = hash_diff(
        source,
        target,
        "src.orders",
        "tgt.orders",
        key_columns=["id"],
        compare_columns=["amount", "status"],
        max_partition_rows=2,
    )
    assert result["algorithm"] == "HASH_DIFF"
    assert result["status"] == "FAIL"
    assert result["raw_rows_retrieved"] == 0
    assert result["partitions"] > 1
    assert result["changed_keys"] == [[2]]
    assert result["missing_keys"] == [[3]]
    assert result["extra_keys"] == [[5]]


def test_cascade_profiles_then_hashes_cross_connector_instances():
    connection = _duckdb_fixture()
    engine = WarehouseDiffEngine(DuckDBConnector(connection), DuckDBConnector(connection))
    result = engine.cascade(
        "src.orders",
        "tgt.orders",
        key_columns=["id"],
        compare_columns=["amount", "status"],
        max_partition_rows=2,
    )
    assert result["algorithm"] == "CASCADE"
    assert result["profile"]["status"] == "FAIL"
    assert result["hash"]["status"] == "FAIL"
    assert result["detail"] is None
    assert result["raw_rows_retrieved"] == 0


def test_cross_warehouse_join_fallback_is_bounded_sqlite_to_duckdb():
    sqlite_connection = sqlite3.connect(":memory:")
    sqlite_connection.execute("CREATE TABLE orders(id INTEGER, amount REAL)")
    sqlite_connection.executemany("INSERT INTO orders VALUES (?, ?)", [(1, 10.0), (2, 20.0)])
    sqlite_connection.commit()

    duck_connection = duckdb.connect(":memory:")
    duck_connection.execute("CREATE TABLE orders(id INTEGER, amount DOUBLE)")
    duck_connection.execute("INSERT INTO orders VALUES (1, 10.0), (2, 21.0)")

    result = join_diff(
        SQLiteConnector(sqlite_connection),
        DuckDBConnector(duck_connection),
        "main.orders",
        "main.orders",
        key_columns=["id"],
        compare_columns=["amount"],
        row_sample_limit=10,
    )
    assert result["execution"] == "BOUNDED_CROSS_WAREHOUSE_FALLBACK"
    assert result["status"] == "FAIL"
    assert result["counts"]["changed"] == 1
    assert result["raw_rows_retrieved"] == 4


def test_diff_plan_selects_join_for_same_connector_and_cascade_for_cross():
    connection = _duckdb_fixture()
    connector = DuckDBConnector(connection)
    same = WarehouseDiffEngine(connector, connector).plan(
        "src.orders", "tgt.orders", key_columns=["id"]
    )
    cross = WarehouseDiffEngine(DuckDBConnector(connection), DuckDBConnector(connection)).plan(
        "src.orders", "tgt.orders", key_columns=["id"]
    )
    assert same["algorithm"] == "JOIN_DIFF"
    assert cross["algorithm"] == "CASCADE"


def test_hash_diff_covers_null_keys_without_skipping_rows():
    connection = duckdb.connect(":memory:")
    connection.execute("CREATE SCHEMA src")
    connection.execute("CREATE SCHEMA tgt")
    connection.execute("CREATE TABLE src.items(id INTEGER, value VARCHAR)")
    connection.execute("CREATE TABLE tgt.items(id INTEGER, value VARCHAR)")
    connection.execute("INSERT INTO src.items VALUES (NULL, 'left'), (1, 'same')")
    connection.execute("INSERT INTO tgt.items VALUES (NULL, 'right'), (1, 'same')")
    connector = DuckDBConnector(connection)

    result = hash_diff(
        connector,
        connector,
        "src.items",
        "tgt.items",
        key_columns=["id"],
        compare_columns=["value"],
        max_partition_rows=10,
    )

    assert result["status"] == "FAIL"
    assert result["changed_keys"] == [[None]]
    assert result["raw_rows_retrieved"] == 0


def test_hash_diff_detects_duplicate_key_multiplicity():
    connection = duckdb.connect(":memory:")
    connection.execute("CREATE SCHEMA src")
    connection.execute("CREATE SCHEMA tgt")
    connection.execute("CREATE TABLE src.items(id INTEGER, value VARCHAR)")
    connection.execute("CREATE TABLE tgt.items(id INTEGER, value VARCHAR)")
    connection.execute("INSERT INTO src.items VALUES (1, 'same'), (1, 'same')")
    connection.execute("INSERT INTO tgt.items VALUES (1, 'same')")
    connector = DuckDBConnector(connection)

    result = hash_diff(
        connector,
        connector,
        "src.items",
        "tgt.items",
        key_columns=["id"],
        compare_columns=["value"],
        max_partition_rows=10,
    )

    assert result["status"] == "FAIL"
    assert result["changed_keys"] == [[1]]


def test_join_diff_uses_presence_sentinels_for_nullable_keys():
    connection = duckdb.connect(":memory:")
    connection.execute("CREATE SCHEMA src")
    connection.execute("CREATE SCHEMA tgt")
    connection.execute("CREATE TABLE src.items(id INTEGER, value VARCHAR)")
    connection.execute("CREATE TABLE tgt.items(id INTEGER, value VARCHAR)")
    connection.execute("INSERT INTO src.items VALUES (NULL, 'same'), (1, 'left')")
    connection.execute("INSERT INTO tgt.items VALUES (NULL, 'same'), (1, 'right')")
    connector = DuckDBConnector(connection)

    result = join_diff(
        connector,
        connector,
        "src.items",
        "tgt.items",
        key_columns=["id"],
        compare_columns=["value"],
    )

    assert result["status"] == "FAIL"
    assert result["counts"] == {"missing": 0, "extra": 0, "changed": 1}


def test_hash_diff_empty_tables_is_deterministic_pass():
    connection = duckdb.connect(":memory:")
    connection.execute("CREATE SCHEMA src")
    connection.execute("CREATE SCHEMA tgt")
    connection.execute("CREATE TABLE src.items(id INTEGER, value VARCHAR)")
    connection.execute("CREATE TABLE tgt.items(id INTEGER, value VARCHAR)")
    connector = DuckDBConnector(connection)

    first = hash_diff(connector, connector, "src.items", "tgt.items", key_columns=["id"], compare_columns=["value"])
    second = hash_diff(connector, connector, "src.items", "tgt.items", key_columns=["id"], compare_columns=["value"])

    assert first == second
    assert first["status"] == "PASS"
    assert first["partitions"] == 0
    assert first["raw_rows_retrieved"] == 0
