import duckdb
import pytest

from app.services.adapters.duckdb_adapter import DuckDBAdapter


@pytest.fixture()
def warehouse(tmp_path):
    path = tmp_path / "warehouse.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t (id INTEGER, val VARCHAR)")
    con.execute("INSERT INTO t VALUES (1, 'a'), (2, 'b'), (NULL, 'c')")
    con.close()
    return path


def test_connection_ok(warehouse):
    adapter = DuckDBAdapter(warehouse)
    assert adapter.test_connection() is True


def test_connection_fails_for_missing_file(tmp_path):
    adapter = DuckDBAdapter(tmp_path / "does_not_exist.duckdb")
    assert adapter.test_connection() is False


def test_get_row_count(warehouse):
    adapter = DuckDBAdapter(warehouse)
    assert adapter.get_row_count("t") == 3
    assert adapter.get_row_count("t", predicate="id IS NOT NULL") == 2


def test_execute_query_real(warehouse):
    adapter = DuckDBAdapter(warehouse)
    result = adapter.execute_query("SELECT count(*) AS failing_count FROM t WHERE id IS NULL")
    assert result.scalar() == 1


def test_get_schema(warehouse):
    adapter = DuckDBAdapter(warehouse)
    cols = adapter.get_schema("t")
    names = [c.name for c in cols]
    assert "id" in names and "val" in names
