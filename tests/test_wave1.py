import json
from pathlib import Path
import pytest

from agentic_data_platform.dbt.adapter import LocalDbtProjectAdapter
from agentic_data_platform.migration.sqlserver_snowflake import plan_sqlserver_to_snowflake
from agentic_data_platform.models import ApprovalRecord, Capability, Environment, Platform, ProjectRecord, Risk, RunRecord, RunState, ToolRequest, VerificationFinding
from agentic_data_platform.orchestration.state_machine import RunStateMachine
from agentic_data_platform.persistence.sqlite import SQLiteControlPlaneRepository
from agentic_data_platform.policy import PolicyEngine
from agentic_data_platform.services.execution import GovernedExecutionService
from agentic_data_platform.sql.engine import analyze_sql, identify_dialect
from agentic_data_platform.tools.registry import ToolDefinition, ToolInvocation, ToolRegistry
from agentic_data_platform.verification.checks import DataSnapshot, synthetic_reconciliation
from agentic_data_platform.verification.engine import VerificationEngine, VerificationGate

DDL = """CREATE TABLE [dbo].[Orders] (
  [OrderId] INT NOT NULL,
  [CustomerId] UNIQUEIDENTIFIER NOT NULL,
  [IsActive] BIT,
  [Description] NVARCHAR(200),
  [CreatedAt] DATETIME2,
  [Amount] DECIMAL(12,2)
);"""
FIXTURE = Path(__file__).parent / "fixtures" / "dbt" / "manifest.json"

def test_prod_mutation_requires_approval():
    decision=PolicyEngine().evaluate(ToolRequest("snowflake","create_table",Environment.PROD,Risk.MUTATING)); assert decision.allowed and decision.requires_approval

def test_destructive_is_denied():
    assert not PolicyEngine().evaluate(ToolRequest("warehouse","drop_database",Environment.DEV,Risk.DESTRUCTIVE)).allowed

def test_state_machine_happy_path_and_repair_budget():
    sm=RunStateMachine()
    for state in [RunState.DISCOVERING,RunState.PLANNING,RunState.GENERATING,RunState.VERIFYING,RunState.EXECUTING,RunState.SUCCEEDED]: sm.transition(state)
    assert sm.state is RunState.SUCCEEDED
    sm=RunStateMachine(max_repairs=1); sm.state=RunState.VERIFYING; sm.transition(RunState.REPAIRING); sm.transition(RunState.VERIFYING)
    with pytest.raises(RuntimeError): sm.transition(RunState.REPAIRING)

def test_verification_fails_closed():
    def broken(): raise RuntimeError("dry-run unavailable")
    report=VerificationEngine().run([lambda: VerificationFinding("compile",True),broken]); assert not report.passed and len(report.findings)==2

def test_ordered_verification_stops_on_blocking_failure():
    called=[]
    def first(): called.append("first"); return VerificationFinding("first",False)
    def second(): called.append("second"); return VerificationFinding("second",True)
    report=VerificationEngine().run_ordered([VerificationGate("first",first),VerificationGate("second",second)]); assert not report.passed and called==["first"]

def test_sqlite_persists_run_and_approval(tmp_path):
    repo=SQLiteControlPlaneRepository(tmp_path/"ade.db"); repo.initialize(); project=ProjectRecord("demo"); repo.save_project(project); run=RunRecord(project.project_id,"env_demo","migrate orders"); repo.save_run(run); repo.save_approval(ApprovalRecord(run.run_id,"reviewer","production_mutation")); assert repo.get_run(run.run_id).intent=="migrate orders" and repo.has_approval(run.run_id,"production_mutation")

def test_durable_evidence_tables_exist(tmp_path):
    repo=SQLiteControlPlaneRepository(tmp_path/"ade.db"); repo.initialize(); assert repo.list_records("generated_artifacts")==[] and repo.list_records("verification_reports")==[] and repo.list_records("execution_evidence")==[]

def test_tool_registry_blocks_prod_bypass():
    registry=ToolRegistry(); registry.register(ToolDefinition("warehouse.execute",Capability.EXECUTE,Risk.MUTATING,frozenset({Platform.SNOWFLAKE}),lambda args:{"ok":True},supports_dry_run=True)); request=ToolRequest("warehouse.execute","create_table",Environment.PROD,Risk.MUTATING,platform=Platform.SNOWFLAKE)
    with pytest.raises(PermissionError,match="approval"): registry.invoke(ToolInvocation(request,"run_1"))
    assert registry.invoke(ToolInvocation(request,"run_1",approved=True))["ok"]

def test_tool_registry_denies_destructive_even_if_approved():
    registry=ToolRegistry(); registry.register(ToolDefinition("warehouse.drop",Capability.EXECUTE,Risk.DESTRUCTIVE,frozenset({Platform.SNOWFLAKE}),lambda args:{"ok":True})); request=ToolRequest("warehouse.drop","drop_database",Environment.DEV,Risk.DESTRUCTIVE,platform=Platform.SNOWFLAKE)
    with pytest.raises(PermissionError,match="blocked"): registry.invoke(ToolInvocation(request,"run_1",approved=True))

def test_sql_analysis_dialect_ddl_dependency_and_safety():
    sql="CREATE TABLE [dbo].[Orders] ([id] INT NOT NULL, [name] NVARCHAR(50), [created] DATETIME2);"; analysis=analyze_sql(sql); assert identify_dialect(sql)=="sqlserver" and analysis.parseable and analysis.safe and len(analysis.objects[0].columns)==3
    assert analyze_sql("select * from analytics.orders o join core.customers c on o.customer_id=c.id").dependencies==("analytics.orders","core.customers")
    assert not analyze_sql("DROP DATABASE production;").safe
    assert not analyze_sql("CREATE TABLE x (id INT").parseable

def test_sqlserver_to_snowflake_offline_plan_and_mappings():
    spec=plan_sqlserver_to_snowflake(DDL); obj=spec.objects[0]; mapping={m.source_name:m.target_type for m in obj.column_mappings}; assert spec.source_platform is Platform.SQLSERVER and spec.target_platform is Platform.SNOWFLAKE; assert mapping["OrderId"]=="NUMBER(38,0)" and mapping["CustomerId"]=="VARCHAR(36)" and mapping["IsActive"]=="BOOLEAN" and mapping["CreatedAt"]=="TIMESTAMP_NTZ"; target=analyze_sql(obj.target_ddl_candidate,"snowflake"); assert target.safe and target.parseable

def test_synthetic_reconciliation_passes_and_detects_mismatch():
    source=DataSnapshot({"ID":"NUMBER","NAME":"VARCHAR"},100,"abc"); target=DataSnapshot({"ID":"NUMBER","NAME":"VARCHAR"},100,"abc"); findings=synthetic_reconciliation(source,target); report=VerificationEngine().run([lambda item=item:item for item in findings]); assert report.passed
    mismatch=synthetic_reconciliation(DataSnapshot({"ID":"NUMBER"},100),DataSnapshot({"ID":"NUMBER"},99)); assert any(f.check=="row_count_parity" and not f.passed for f in mismatch)

def test_dbt_manifest_downstream_and_command_construction(tmp_path):
    adapter=LocalDbtProjectAdapter(tmp_path); manifest=json.loads(FIXTURE.read_text()); assert adapter.list_sources(manifest)==["source.demo.raw.orders"]; assert adapter.downstream(manifest,"model.demo.stg_orders")==["model.demo.fct_orders","model.demo.order_metrics","test.demo.not_null_orders"]; command=adapter.test_command("model.demo.stg_orders+"); assert command.argv[:2]==("dbt","test") and "--select" in command.argv

def test_governed_execution_uses_persisted_approval_and_records_evidence(tmp_path):
    repo=SQLiteControlPlaneRepository(tmp_path/"ade.db"); repo.initialize(); project=ProjectRecord("demo"); repo.save_project(project); run=RunRecord(project.project_id,"prod","create table"); repo.save_run(run); registry=ToolRegistry(); registry.register(ToolDefinition("snowflake.execute",Capability.EXECUTE,Risk.MUTATING,frozenset({Platform.SNOWFLAKE}),lambda args:{"status":"ok"})); service=GovernedExecutionService(registry,repo); request=ToolRequest("snowflake.execute","create_table",Environment.PROD,Risk.MUTATING,platform=Platform.SNOWFLAKE)
    with pytest.raises(PermissionError): service.execute(run.run_id,request)
    repo.save_approval(ApprovalRecord(run.run_id,"reviewer","production_mutation")); assert service.execute(run.run_id,request)["status"]=="ok" and len(repo.list_records("execution_evidence",run_id=run.run_id))==1
