"""Real, live DataPlatformAdapter implementation for DuckDB -- the only
warehouse adapter that is fully implemented and executes real queries in
this phase. Connects read-only to a local DbtProject's own warehouse file
(the same one `dbt build` writes to), so quality rules see exactly what the
last dbt run produced.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from .base import ColumnSchema, DataPlatformAdapter, QueryResult


class DuckDBAdapter(DataPlatformAdapter):
    dialect = "duckdb"

    def __init__(self, warehouse_path: str | Path):
        self.warehouse_path = str(warehouse_path)

    def test_connection(self) -> bool:
        try:
            con = duckdb.connect(self.warehouse_path, read_only=True)
            con.execute("select 1")
            con.close()
            return True
        except duckdb.Error:
            return False

    def _connect(self):
        return duckdb.connect(self.warehouse_path, read_only=True)

    def get_row_count(self, table: str, predicate: str | None = None) -> int:
        where = f" WHERE {predicate}" if predicate else ""
        con = self._connect()
        try:
            return con.execute(f"SELECT count(*) FROM {table}{where}").fetchone()[0]
        finally:
            con.close()

    def get_schema(self, table: str) -> list[ColumnSchema]:
        con = self._connect()
        try:
            rows = con.execute(f"DESCRIBE {table}").fetchall()
            # DESCRIBE columns: column_name, column_type, null, key, default, extra
            return [ColumnSchema(name=r[0], data_type=r[1], nullable=(r[2] == "YES")) for r in rows]
        finally:
            con.close()

    def execute_query(self, sql: str) -> QueryResult:
        con = self._connect()
        try:
            cursor = con.execute(sql)
            columns = [d[0] for d in cursor.description]
            rows = cursor.fetchall()
            return QueryResult(columns=columns, rows=rows)
        finally:
            con.close()


def resolve_duckdb_adapter_for_project(project) -> DuckDBAdapter:
    """`project` is a DbtProject row with execution_mode == "local" and
    adapter == "duckdb". Raises if the project isn't in that shape --
    callers should check first."""
    if project.execution_mode != "local" or project.adapter != "duckdb":
        raise ValueError(f"project {project.id} is not a local DuckDB project")
    warehouse_path = Path(project.project_dir) / "warehouse" / "warehouse.duckdb"
    if not warehouse_path.exists():
        raise FileNotFoundError(
            f"no warehouse file at {warehouse_path} -- run a dbt build for this project first"
        )
    return DuckDBAdapter(warehouse_path)
