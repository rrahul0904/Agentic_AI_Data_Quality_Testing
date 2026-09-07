from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from agentic_data_platform.agents.planner import PlannerAgent
from agentic_data_platform.agents.repair import RepairAgent
from agentic_data_platform.api.app import create_app
from agentic_data_platform.connectors.bigquery import BigQueryConfig, BigQueryConnector
from agentic_data_platform.connectors.capabilities import ConnectorCapability
from agentic_data_platform.connectors.databricks import DatabricksConfig, DatabricksConnector
from agentic_data_platform.connectors.registry import ConnectorRegistry
from agentic_data_platform.connectors.snowflake import SnowflakeConfig, SnowflakeConnector
from agentic_data_platform.context.graph import ContextGraph, GraphNode
from agentic_data_platform.dbt.intelligence import get_changed_nodes, get_downstream_nodes, get_upstream_nodes, selective_build_command, state_test_command
from agentic_data_platform.migrations.checkpoints import CheckpointStore
from agentic_data_platform.migrations.models import MigrationObject, MigrationStatus, MigrationWave
from agentic_data_platform.migrations.reconciliation import PartitionMetrics, reconcile_partitions
from agentic_data_platform.migrations.waves import MigrationWaveExecutor
from agentic_data_platform.models import ApprovalRecord, Environment, RunRecord
from agentic_data_platform.persistence.sqlite import SQLiteControlPlaneRepository
from agentic_data_platform.schema.drift import DriftCategory, SchemaChangeAnalyzer, SchemaColumn
from agentic_data_platform.sql.dependencies import target_tables, tables_referenced, upstream_tables
from agentic_data_platform.sql.parser import parse_sql
from agentic_data_platform.sql.safety import classify_mutation, is_hard_denied, validate_single_statement


class FakeQuery:
    def __init__(self, rows, columns=()):
        self._rows = rows
        self.description = [(column,) for column in columns]

    def fetchall(self):
        return self._rows


def test_snowflake_read_only_metadata_and_ddl():
    statements = []

    def execute(sql):
        statements.append(sql)
        if sql.startswith("SHOW SCHEMAS"):
            return {"rows": [{"name": "PUBLIC"}]}
        if sql.startswith("SHOW TABLES"):
            return {"rows": [{"name": "ORDERS", "kind": "TABLE"}]}
        if sql.startswith("DESC"):
            return {"rows": [{"name": "ID", "type": "NUMBER", "null?": "N", "kind": "COLUMN"}]}
        if sql.startswith("SELECT GET_DDL"):
            return {"rows": [{"ddl": "CREATE TABLE ORDERS (ID NUMBER)"}]}
        return {"rows": [{"ID": 1}], "columns": ["ID"]}

    connector = SnowflakeConnector(execute, SnowflakeConfig(database="DEMO"))
    assert connector.list_schemas()[0].name == "PUBLIC"
    assert connector.list_tables("PUBLIC")[0].qualified_name == "DEMO.PUBLIC.ORDERS"
    assert connector.describe_table("PUBLIC", "ORDERS").columns[0].nullable is False
    assert connector.get_ddl("PUBLIC", "ORDERS").startswith("CREATE")
    assert connector.execute_read("SELECT 1").rows == ({"ID": 1},)
    with pytest.raises(PermissionError):
        connector.execute_read("DELETE FROM ORDERS")
    assert ConnectorCapability.GET_DDL in connector.capabilities()
    assert all("PASSWORD" not in statement for statement in statements)


def test_databricks_read_only_metadata():
    def execute(sql):
        if sql == "SHOW CATALOGS":
            return {"rows": [{"catalog": "main"}]}
        if sql.startswith("SHOW SCHEMAS"):
            return {"rows": [{"databaseName": "analytics"}]}
        if sql.startswith("SHOW TABLES"):
            return {"rows": [{"tableName": "orders", "isTemporary": False}]}
        if sql.startswith("DESCRIBE"):
            return {"rows": [{"col_name": "id", "data_type": "BIGINT", "comment": ""}]}
        return {"rows": []}

    connector = DatabricksConnector(execute, DatabricksConfig(catalog="main"))
    assert connector.list_catalogs() == ["main"]
    assert connector.list_schemas() == [connector.list_schemas()[0]]
    assert connector.list_tables("analytics")[0].name == "orders"
    assert connector.describe_table("analytics", "orders").columns[0].data_type == "BIGINT"
    assert connector.dry_run_sql("SELECT 1").valid
    with pytest.raises(PermissionError):
        connector.dry_run_sql("CREATE TABLE x(id int)")


class FakeBqJob:
    job_id = "job-1"
    total_bytes_processed = 1024**4

    def result(self):
        return [{"id": 1}]


class FakeBqClient:
    def __init__(self):
        self.calls = []

    def query(self, sql, **kwargs):
        self.calls.append((sql, kwargs))
        return FakeBqJob()

    def list_projects(self):
        return [type("Project", (), {"project_id": "demo"})()]

    def list_datasets(self, project):
        return [type("Dataset", (), {"dataset_id": "analytics"})()]

    def list_tables(self, dataset):
        return [type("Table", (), {"table_id": "orders", "table_type": "TABLE"})()]

    def get_table(self, name):
        field = type("Field", (), {"name": "id", "field_type": "INT64", "mode": "REQUIRED", "precision": None, "scale": None})()
        return type("Table", (), {"schema": [field], "view_query": None})()


def test_bigquery_dry_run_and_metadata_without_google_sdk():
    client = FakeBqClient()
    connector = BigQueryConnector(client, BigQueryConfig("demo"))
    result = connector.dry_run_sql("SELECT * FROM analytics.orders")
    assert result.valid and result.estimated_bytes == 1024**4 and result.estimated_cost == Decimal("6")
    assert connector.list_catalogs() == ["demo"]
    assert connector.list_schemas()[0].name == "analytics"
    assert connector.list_tables("analytics")[0].name == "orders"
    assert connector.describe_table("analytics", "orders").columns[0].nullable is False
    assert connector.execute_read("SELECT 1").rows == ({"id": 1},)
    with pytest.raises(PermissionError):
        connector.execute_read("UPDATE orders SET id = 2")


def test_connector_registry_rejects_duplicate_registration():
    registry = ConnectorRegistry()
    connector = SnowflakeConnector(lambda _: {"rows": []}, SnowflakeConfig(database="DEMO"))
    registry.register("demo", connector)
    assert registry.get("demo") is connector and registry.names() == ("demo",)
    with pytest.raises(ValueError):
        registry.register("demo", connector)
    with pytest.raises(KeyError):
        registry.get("missing")


@pytest.mark.parametrize(
    ("prefix", "config_type", "values"),
    [
        ("ADE_SNOWFLAKE", SnowflakeConfig, {"ACCOUNT": "account", "USER": "user", "DATABASE": "database", "SCHEMA": "schema", "WAREHOUSE": "warehouse", "ROLE": "role"}),
        ("ADE_DATABRICKS", DatabricksConfig, {"HOST": "host", "TOKEN": "token", "HTTP_PATH": "path", "CATALOG": "catalog"}),
        ("ADE_BIGQUERY", BigQueryConfig, {"PROJECT": "project"}),
    ],
)
def test_connector_config_reads_environment_without_logging(monkeypatch, prefix, config_type, values):
    for key, value in values.items():
        monkeypatch.setenv(f"{prefix}_{key}", value)
    config = config_type.from_env()
    for key, value in values.items():
        assert getattr(config, key.lower()) == value


@pytest.mark.parametrize(
    ("sql", "classification", "hard_denied"),
    [
        ("SELECT * FROM x", "read", False),
        ("WITH x AS (SELECT 1) SELECT * FROM x", "read", False),
        ("INSERT INTO x SELECT 1", "mutating", False),
        ("MERGE INTO x USING y ON 1=1 WHEN MATCHED THEN UPDATE SET id=1", "mutating", False),
        ("UPDATE x SET id = 1", "mutating", False),
        ("DELETE FROM x", "mutating", False),
        ("CREATE TABLE x (id INT)", "mutating", False),
        ("ALTER TABLE x ADD COLUMN y INT", "mutating", False),
        ("DROP TABLE x", "mutating", False),
        ("DROP SCHEMA x", "mutating", True),
        ("DROP DATABASE x", "mutating", True),
        ("TRUNCATE TABLE x", "mutating", True),
    ],
)
def test_sql_operation_classification(sql, classification, hard_denied):
    assert classify_mutation(sql) == classification
    assert is_hard_denied(sql) is hard_denied


@pytest.mark.parametrize(
    ("sql", "statement", "tables"),
    [
        ("SELECT id FROM core.orders", "SELECT", ("core.orders",)),
        ("SELECT * FROM a JOIN b ON a.id=b.id", "SELECT", ("a", "b")),
        ("WITH x AS (SELECT * FROM raw.x) SELECT * FROM x", "WITH", ("raw.x",)),
        ("INSERT INTO dst SELECT * FROM src", "INSERT", ("src", "dst")),
        ("UPDATE dst SET id=1", "UPDATE", ("dst",)),
        ("DELETE FROM dst", "DELETE", ("dst",)),
        ("CREATE TABLE dst (id INT)", "CREATE", ("dst",)),
        ("DROP TABLE dst", "DROP", ("dst",)),
    ],
)
def test_sql_ast_and_dependency_helpers(sql, statement, tables):
    ast = parse_sql(sql)
    assert ast.statement_type == statement and ast.tables == tables
    assert tables_referenced(sql) == tables
    assert validate_single_statement(sql)


def test_sql_target_and_source_dependencies():
    sql = "INSERT INTO dst SELECT * FROM src JOIN dim ON src.id=dim.id"
    assert upstream_tables(sql) == ("src", "dim")
    assert target_tables(sql) == ("dst",)
    assert not validate_single_statement("SELECT 1; SELECT 2")


@pytest.mark.parametrize(
    ("sql", "ctes", "joins", "functions"),
    [
        ("SELECT COUNT(*) FROM orders", (), (), ("COUNT",)),
        ("SELECT COALESCE(name, 'x') FROM orders", (), (), ("COALESCE",)),
        ("WITH x AS (SELECT * FROM orders) SELECT * FROM x", ("x",), (), ()),
        ("SELECT * FROM orders JOIN customers ON 1=1", (), ("customers",), ()),
        ("WITH x AS (SELECT SUM(amount) FROM orders) SELECT * FROM x JOIN customers ON 1=1", ("x",), ("customers",), ("SUM",)),
    ],
)
def test_sql_ast_exposes_structural_details(sql, ctes, joins, functions):
    ast = parse_sql(sql)
    assert ast.ctes == ctes and ast.joins == joins
    assert all(function in ast.functions for function in functions)


def test_context_graph_persists_and_traverses(tmp_path):
    graph = ContextGraph(tmp_path / "graph.db")
    source = graph.upsert_node(GraphNode("Table", "raw.customers"))
    model = graph.upsert_node(GraphNode("dbtModel", "stg_customers"))
    dashboard = graph.upsert_node(GraphNode("Pipeline", "customer_metrics"))
    graph.upsert_edge(source_id=source.node_id, target_id=model.node_id, edge_type="READS_FROM")
    graph.upsert_edge(source_id=model.node_id, target_id=dashboard.node_id, edge_type="PRODUCES")
    assert [node.name for node in graph.downstream(source.node_id)] == ["stg_customers", "customer_metrics"]
    assert [node.name for node in graph.upstream(dashboard.node_id)] == ["stg_customers", "raw.customers"]
    assert graph.impact(source.node_id)[-1].name == "customer_metrics"
    with pytest.raises(ValueError):
        graph.upsert_edge(source_id="missing", target_id=model.node_id, edge_type="READS_FROM")


def test_context_graph_upserts_stable_node_and_edge(tmp_path):
    graph = ContextGraph(tmp_path / "graph.db")
    source = graph.upsert_node(kind="Table", name="raw.orders", properties={"owner": "analytics"})
    refreshed = graph.upsert_node(kind="Table", name="raw.orders", properties={"owner": "platform"})
    target = graph.upsert_node(kind="dbtModel", name="stg_orders")
    edge = graph.upsert_edge(source_id=source.node_id, target_id=target.node_id, edge_type="READS_FROM")
    updated = graph.upsert_edge(source_id=source.node_id, target_id=target.node_id, edge_type="READS_FROM", properties={"sql": "select"})
    assert source.node_id == refreshed.node_id and edge.edge_id == updated.edge_id
    assert graph.get_node(source.node_id).properties == {"owner": "platform"}


def test_migration_wave_orders_checkpoints_and_resume(tmp_path):
    store = CheckpointStore(tmp_path / "migration.db")
    customers = MigrationObject("customers")
    orders = MigrationObject("orders", dependencies=("customers",))
    wave = MigrationWave("wave-1", (orders, customers))
    invoked = []
    report = MigrationWaveExecutor(store).execute(wave, lambda obj, phase: invoked.append((obj.name, phase)) or {"phase": phase})
    assert report.status is MigrationStatus.COMPLETED
    assert [name for name, phase in invoked if phase == "DDL"] == ["customers", "orders"]
    resumed = MigrationWaveExecutor(store).resume_wave(wave, lambda obj, phase: pytest.fail("completed checkpoint should skip action"))
    assert resumed.skipped_objects == ("customers", "orders")


def test_migration_wave_stops_after_failure(tmp_path):
    store = CheckpointStore(tmp_path / "migration.db")
    first, second = MigrationObject("first"), MigrationObject("second", dependencies=("first",))
    wave = MigrationWave("wave", (first, second))
    report = MigrationWaveExecutor(store).execute(wave, lambda obj, phase: (_ for _ in ()).throw(RuntimeError("broken")) if obj.name == "first" and phase == "TRANSFER" else {})
    assert report.status is MigrationStatus.FAILED and report.failed_object == "first"
    assert not store.completed(wave.wave_id, second.object_id, "DDL")


def test_migration_wave_blocks_cycles(tmp_path):
    first, second = MigrationObject("first", dependencies=("second",)), MigrationObject("second", dependencies=("first",))
    report = MigrationWaveExecutor(CheckpointStore(tmp_path / "migration.db")).execute(MigrationWave("cycle", (first, second)), lambda *_: {})
    assert report.status is MigrationStatus.BLOCKED


@pytest.mark.parametrize(
    ("source", "target", "passed"),
    [
        ([PartitionMetrics("2026-01", 1, hash_value="a")], [PartitionMetrics("2026-01", 1, hash_value="a")], True),
        ([PartitionMetrics("2026-01", 1)], [PartitionMetrics("2026-01", 2)], False),
        ([PartitionMetrics("2026-01", 1)], [], False),
        ([], [PartitionMetrics("2026-01", 1)], False),
        ([PartitionMetrics("a", 1), PartitionMetrics("b", 2)], [PartitionMetrics("a", 1), PartitionMetrics("b", 2)], True),
    ],
)
def test_partition_reconciliation(source, target, passed):
    results = reconcile_partitions(source, target)
    assert all(item.passed for item in results) is passed


@pytest.mark.parametrize(
    ("before", "after", "category"),
    [
        ([], [SchemaColumn("new", "VARCHAR(20)")], DriftCategory.SAFE),
        ([], [SchemaColumn("new", "VARCHAR(20)", nullable=False)], DriftCategory.BREAKING),
        ([SchemaColumn("old", "INT")], [], DriftCategory.BREAKING),
        ([SchemaColumn("id", "INT")], [SchemaColumn("id", "BIGINT")], DriftCategory.SAFE),
        ([SchemaColumn("id", "BIGINT")], [SchemaColumn("id", "INT")], DriftCategory.BREAKING),
        ([SchemaColumn("email", "VARCHAR(100)")], [SchemaColumn("email", "VARCHAR(50)")], DriftCategory.WARNING),
        ([SchemaColumn("email", "VARCHAR(50)")], [SchemaColumn("email", "VARCHAR(100)")], DriftCategory.SAFE),
        ([SchemaColumn("id", "INT", True)], [SchemaColumn("id", "INT", False)], DriftCategory.BREAKING),
        ([SchemaColumn("id", "INT", False)], [SchemaColumn("id", "INT", True)], DriftCategory.SAFE),
        ([SchemaColumn("id", "INT")], [SchemaColumn("id", "UUID")], DriftCategory.UNKNOWN),
    ],
)
def test_schema_drift_categories(before, after, category):
    report = SchemaChangeAnalyzer.compare(before, after)
    assert report.changes[0].category is category


@pytest.mark.parametrize(
    "column",
    [
        SchemaColumn("id", "INT"),
        SchemaColumn("name", "VARCHAR(20)"),
        SchemaColumn("event_at", "TIMESTAMP"),
        SchemaColumn("amount", "DECIMAL(12,2)"),
        SchemaColumn("enabled", "BOOLEAN", nullable=False),
    ],
)
def test_schema_drift_ignores_identical_columns(column):
    assert SchemaChangeAnalyzer.compare([column], [column]).changes == ()


def test_dbt_changed_impact_and_commands():
    previous = {"nodes": {"model.demo.orders": {"raw_code": "select 1"}}, "child_map": {"model.demo.orders": ["model.demo.metrics"]}, "parent_map": {"model.demo.metrics": ["model.demo.orders"]}}
    current = deepcopy(previous)
    current["nodes"]["model.demo.orders"]["raw_code"] = "select 2"
    current["nodes"]["model.demo.customers"] = {"raw_code": "select 1"}
    assert get_changed_nodes(previous, current) == ["model.demo.customers", "model.demo.orders"]
    assert get_downstream_nodes(current, "model.demo.orders") == ["model.demo.metrics"]
    assert get_upstream_nodes(current, "model.demo.metrics") == ["model.demo.orders"]
    assert selective_build_command("/tmp/project", "model.demo.orders")[-1] == "model.demo.orders+"
    assert state_test_command("/tmp/project")[-1] == "state:modified+"


def test_planner_and_bounded_repair_agent():
    plan = PlannerAgent().propose_migration("Migrate customers", "sqlserver", "snowflake", ("customers",))
    assert plan.migration_waves == (("customers",),) and "migration-wave execution" in plan.approval_points
    calls = []
    attempts = RepairAgent(max_attempts=3).repair(lambda: "hash mismatch", lambda diagnosis, number: (calls.append(number) and "patch.sql", {"attempt": number}, number == 2))
    assert [attempt.number for attempt in attempts] == [1, 2] and calls == [1, 2]
    with pytest.raises(ValueError):
        RepairAgent(0)


def test_expired_and_environment_mismatched_approval_are_denied(tmp_path):
    repo = SQLiteControlPlaneRepository(tmp_path / "control.db")
    repo.initialize()
    run = RunRecord("project", "prod", "migration")
    repo.save_run(run)
    expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    repo.save_approval(ApprovalRecord(run.run_id, "reviewer", "wave", environment=Environment.PROD, expires_at=expired))
    assert not repo.has_approval(run.run_id, "wave", environment="prod")
    repo.save_approval(ApprovalRecord(run.run_id, "reviewer", "wave", environment=Environment.DEV))
    assert not repo.has_approval(run.run_id, "wave", environment="prod")
    assert repo.has_approval(run.run_id, "wave", environment="dev")


def test_rest_api_core_workflows(tmp_path):
    repo = SQLiteControlPlaneRepository(tmp_path / "api.db")
    client = TestClient(create_app(repo))
    created = client.post("/projects", json={"name": "demo"})
    assert created.status_code == 200
    project = created.json()
    assert client.get("/projects").json()[0]["name"] == "demo"
    run = client.post("/runs", json={"project_id": project["project_id"], "environment_id": "dev", "intent": "discover"}).json()
    assert client.get("/runs").json()[0]["run_id"] == run["run_id"]
    assert client.get(f"/runs/{run['run_id']}").status_code == 200
    assert client.get("/runs/missing").status_code == 404
    assert client.post("/discover").json()["status"] == "accepted"
    migration = client.post("/migrations/plan", json={"intent": "migrate", "source": "sqlserver", "target": "snowflake", "objects": ["orders"]})
    assert migration.status_code == 200 and migration.json()["migration_waves"] == [["orders"]]
    assert client.post("/migrations/wave-1/execute").json()["status"] == "approval_required"
    assert client.post("/verify", json={"sql": "SELECT 1"}).json()["parseable"]
    approval = client.post("/approvals", json={"run_id": run["run_id"], "approved_by": "reviewer", "scope": "wave"}).json()
    assert client.get("/approvals").json()[0]["approval_id"] == approval["approval_id"]
    assert client.get(f"/approvals/{approval['approval_id']}").status_code == 200
    assert client.get("/approvals/missing").status_code == 404


def test_connector_requires_discovery_context():
    with pytest.raises(ValueError):
        SnowflakeConnector(lambda _: {"rows": []}).list_schemas()
    with pytest.raises(ValueError):
        BigQueryConnector(FakeBqClient()).list_schemas()


def test_graph_rejects_unknown_direction(tmp_path):
    graph = ContextGraph(tmp_path / "graph.db")
    node = graph.upsert_node(kind="Table", name="orders")
    with pytest.raises(ValueError):
        graph.neighbors(node.node_id, direction="sideways")


def test_api_rejects_invalid_project_payload(tmp_path):
    client = TestClient(create_app(SQLiteControlPlaneRepository(tmp_path / "api.db")))
    assert client.post("/projects", json={"name": ""}).status_code == 422


def test_api_verification_reports_unparseable_sql(tmp_path):
    client = TestClient(create_app(SQLiteControlPlaneRepository(tmp_path / "api.db")))
    response = client.post("/verify", json={"sql": ""})
    assert response.status_code == 200 and response.json()["parseable"] is False


def test_default_api_uses_configured_persistent_database(tmp_path, monkeypatch):
    database = tmp_path / "control-plane.db"
    monkeypatch.setenv("ADE_DATABASE_PATH", str(database))
    first = TestClient(create_app())
    first.post("/projects", json={"name": "durable-demo"})
    second = TestClient(create_app())
    assert second.get("/projects").json()[0]["name"] == "durable-demo"
