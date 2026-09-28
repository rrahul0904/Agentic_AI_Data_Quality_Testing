import assert from "node:assert/strict";
import test from "node:test";
import type { ProjectAnalysisReport } from "../lib/project-analysis.ts";
import { correlateRuntimeExecutions, lineageRuntimeRefresh, type RuntimeExecutionRecord } from "../lib/runtime-status-consistency.ts";

function report(overrides: Partial<ProjectAnalysisReport> = {}): ProjectAnalysisReport {
  return {
    run_id: "analysis-guests", project_id: "data-quality-testing-beta", environment: "development", source_table_scope_id: "postgres:public:guests", status: "PASS", created_at: "2026-09-23T12:00:00Z",
    graph: { nodes: [{ node_id: "dag", kind: "airflow_dag", name: "ingest_guests", properties: {} }, { node_id: "mart", kind: "mart", name: "dim_guest", properties: {} }], edges: [], node_types: {}, edge_types: {} },
    evidence: [], asset_classifications: [], relationship_classifications: [], exceptions: [], agent: {}, analyzers: [], pipelines: [], summary: { assets: 2, relationships: 0, classified_assets: 0, classified_relationships: 0, exceptions: 0, ai_status: "NOT_RUN", top_level_assets: 2, child_assets: 0, pipelines: 0 },
    runtime: { status: "NOT_RUN", refreshed_at: null, lineage_state: "PLANNED", systems: { airflow: { status: "NOT_RUN" }, dbt: { status: "NOT_RUN" }, snowflake: { status: "NOT_RUN" } }, observed_edge_count: 0, observed_node_count: 0 }, ...overrides,
  };
}

function run(overrides: RuntimeExecutionRecord = {}): RuntimeExecutionRecord {
  return { run_id: "action-run-1", execution_status: "COMPLETED", execution_verification_status: "VERIFIED", data_quality_status: "NOT_CHECKED", plan: { project_id: "data-quality-testing-beta", environment: "development", source_table_scope_id: "postgres:public:guests" }, current_step_details: { sequence: 1, asset: "dim_guest", kind: "dbt_execute" }, external_identifiers: [{ technology: "dbt", kind: "invocation_id", value: "invocation-123", step_sequence: 1 }], last_observation: "2026-09-23T14:47:11Z", ...overrides };
}

test("Monitoring links exact scoped runs without changing lineage runtime status", () => {
  const current = report();
  const [reference] = correlateRuntimeExecutions(current, [run()]);
  assert.equal(reference?.assetName, "dim_guest");
  assert.equal(reference?.scopeMatch, "MATCHED");
  assert.equal(reference?.externalIdentifier, "invocation-123");
  assert.equal(reference?.dataQualityStatus, "NOT_CHECKED");
  assert.equal(lineageRuntimeRefresh(current).status, "NOT_RUN");
  assert.equal(lineageRuntimeRefresh(current).observedEdges, 0);
});

test("Monitoring excludes runs from a different explicit source-table scope", () => {
  const mismatched = run({ plan: { project_id: "data-quality-testing-beta", environment: "development", source_table_scope_id: "postgres:public:payments" } });
  assert.deepEqual(correlateRuntimeExecutions(report(), [mismatched]), []);
});

test("Monitoring refuses ambiguous display-name matches", () => {
  const current = report({ graph: { ...report().graph, nodes: [{ node_id: "a", kind: "mart", name: "dim_guest", properties: {} }, { node_id: "b", kind: "dbt_model", name: "dim_guest", properties: {} }], edges: [], node_types: {}, edge_types: {} } });
  assert.deepEqual(correlateRuntimeExecutions(current, [run()]), []);
});
