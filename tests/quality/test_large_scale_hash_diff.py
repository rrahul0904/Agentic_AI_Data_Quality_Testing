from agentic_data_platform.connectors.duckdb import DuckDBConnector
from agentic_data_platform.quality.warehouse_diff import hash_diff


def _connector(rows):
    import duckdb
    connection = duckdb.connect(":memory:")
    connection.execute("CREATE SCHEMA s")
    connection.execute("CREATE TABLE s.items(tenant VARCHAR, id VARCHAR, value INTEGER)")
    connection.executemany("INSERT INTO s.items VALUES (?, ?, ?)", rows)
    return connection, DuckDBConnector(connection)


def test_compound_string_hash_diff_uses_bounded_hash_buckets():
    left_conn, left = _connector([("a", "1", 10), ("a", "2", 20), ("b", "1", 30)])
    right_conn, right = _connector([("a", "1", 10), ("a", "2", 21), ("b", "1", 30)])
    try:
        result = hash_diff(
            left,
            right,
            "s.items",
            "s.items",
            key_columns=["tenant", "id"],
            compare_columns=["value"],
            max_partition_rows=2,
        )
        assert result["partition_strategy"] == "COMPOUND_KEY"
        assert result["status"] == "FAIL"
        assert ["a", "2"] in result["changed_keys"]
        assert result["raw_rows_retrieved"] == 0
        assert result["rows_transferred"] <= 6
    finally:
        left_conn.close()
        right_conn.close()
