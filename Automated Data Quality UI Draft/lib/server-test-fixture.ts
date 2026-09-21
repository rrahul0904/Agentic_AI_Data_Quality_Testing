import { readFile } from "node:fs/promises";
import path from "node:path";

/**
 * Test-only populated state for the browser release gate.
 *
 * This is deliberately disabled by default, including in production. The
 * query flag is accepted only when the operator explicitly starts a test
 * server with ADQ_UI_TEST_FIXTURES=1 and only for the fixture scope.
 * It exists to exercise the real Catalog, Lineage, Rules, and run-detail
 * renderers without seeding fake operational state into a user's project.
 */
export function isPhase4Fixture(request: Request): boolean {
  if (process.env.ADQ_UI_TEST_FIXTURES !== "1") return false;
  const params = new URL(request.url).searchParams;
  return params.get("fixture") === "phase4"
    && params.get("project_id") === "fixture-project"
    && params.get("environment") === "fixture";
}

type Fixture = {
  scope: { project_id: string; environment: string; discovery_snapshot_id: string; plan_id: string; run_id: string };
  catalog: { assets: Array<{ id: string; name: string; kind: string; lineage_state: string }> };
  lineage: { links: Array<{ id: string; source: string; target: string; lineage_state: string }> };
  rules: { items: Array<{ id: string; asset_id: string; state: string; latest_result: string }> };
  monitoring: { states: Array<{ run_id: string; status: string; execution_status: string; verification_status: string; data_quality_status: string; evidence_status: string }> };
};

async function readFixture(): Promise<Fixture> {
  const file = path.join(process.cwd(), "tests", "fixtures", "phase4-populated-state.json");
  return JSON.parse(await readFile(file, "utf8")) as Fixture;
}

export async function phase4AnalysisWorkspace(): Promise<Record<string, unknown>> {
  const fixture = await readFixture();
  const now = "2026-01-01T00:00:00.000Z";
  const evidence = fixture.catalog.assets.map((asset, index) => ({
    evidence_id: `evidence_fixture_${index + 1}`,
    kind: "DISCOVERY",
    source: "TEST_ONLY_UI_FIXTURE",
    maturity: asset.lineage_state === "OBSERVED" ? "OBSERVED" : "DECLARED",
    payload: { asset_id: asset.id, fixture_id: "phase4-populated-operator-console-v1" },
    observed_at: now,
  }));
  const nodes = fixture.catalog.assets.map((asset) => ({
    node_id: asset.id,
    kind: asset.kind,
    name: asset.name,
    properties: {
      is_top_level: true,
      discovery_asset_id: asset.id,
      source_table_id: "fixture_orders",
      connection_kind: asset.kind === "source_table" ? "postgres" : asset.kind === "dbt_model" ? "dbt" : "snowflake",
      lineage_state: asset.lineage_state,
      runtime_status: asset.lineage_state === "OBSERVED" ? "COMPLETED" : "NOT_RUN",
    },
  }));
  const classifications = fixture.catalog.assets.map((asset, index) => ({
    asset_id: asset.id,
    roles: [asset.kind === "source_table" ? "source" : asset.kind === "dbt_model" ? "transformation" : "target"],
    confidence: 1,
    source: "DETERMINISTIC",
    evidence_ids: [evidence[index].evidence_id],
    rationale: "Fixture evidence is limited to browser rendering verification.",
    requires_review: asset.lineage_state !== "OBSERVED",
    status: "DETERMINISTIC",
    lineage_state: asset.lineage_state,
    runtime_status: asset.lineage_state === "OBSERVED" ? "COMPLETED" : "NOT_RUN",
  }));
  const relationships = fixture.lineage.links.map((link) => ({
    edge_id: link.id,
    source_asset_id: link.source,
    target_asset_id: link.target,
    relationship: "transforms_into",
    confidence: 1,
    source: "DETERMINISTIC",
    evidence_ids: [],
    rationale: "Fixture relationship used only for populated-state rendering.",
    requires_review: link.lineage_state !== "OBSERVED",
    status: "DETERMINISTIC",
    pipeline_ids: ["pipeline_fixture_orders"],
    lineage_state: link.lineage_state,
    runtime_status: link.lineage_state === "OBSERVED" ? "COMPLETED" : "NOT_RUN",
  }));
  return {
    report: {
      run_id: "analysis_fixture_001", project_id: fixture.scope.project_id, environment: fixture.scope.environment,
      status: "COMPLETED", created_at: now, graph: { nodes, edges: fixture.lineage.links.map((link) => ({ edge_id: link.id, source_id: link.source, target_id: link.target, edge_type: "transforms_into", properties: {} })), node_types: {}, edge_types: {} },
      evidence, asset_classifications: classifications, relationship_classifications: relationships, exceptions: [], agent: { status: "NOT_INVOKED" }, analyzers: [],
      pipelines: [{ pipeline_id: "pipeline_fixture_orders", name: "orders ingestion and transformation", root_asset_ids: ["asset_source_orders"], node_ids: fixture.catalog.assets.map((asset) => asset.id), edge_ids: fixture.lineage.links.map((link) => link.id), status: "DETERMINISTIC", requires_review: true, technology_kinds: ["postgres", "dbt", "snowflake"] }],
      runtime: { status: "COMPLETED", refreshed_at: now, lineage_state: "OBSERVED", systems: { airflow: { status: "COMPLETED", completed_at: now }, dbt: { status: "COMPLETED", completed_at: now }, snowflake: { status: "COMPLETED", completed_at: now } }, observed_edge_count: 1, observed_node_count: 1, note: "Test-only populated UI state; not an execution record." },
      summary: { assets: 3, relationships: 2, classified_assets: 3, classified_relationships: 2, exceptions: 0, ai_status: "NOT_INVOKED", top_level_assets: 3, child_assets: 0, pipelines: 1 },
    },
    capabilities: { status: "TEST_ONLY_FIXTURE", openai: { status: "UNAVAILABLE" } },
    decisions: { assets: {}, relationships: {} },
    ai_review: null,
    workspace: { projectId: fixture.scope.project_id, environment: fixture.scope.environment },
  };
}

export async function phase4QualityWorkspace(): Promise<Record<string, unknown>> {
  const fixture = await readFixture();
  const now = "2026-01-01T00:00:00.000Z";
  const mapping = { mapping_id: "mapping_fixture_orders", source_asset_id: "asset_source_orders", source_name: "postgres.public.orders", path_asset_ids: ["asset_source_orders", "asset_model_orders"], orchestrator_asset_ids: [], target_asset_id: "asset_target_orders", target_name: "ANALYTICS.RAW.ORDERS", key_column: "order_id", key_columns: ["order_id"], key_inference: "fixture", evidence: "TEST_ONLY_UI_FIXTURE" };
  const checks = fixture.rules.items.map((item) => ({ check_id: item.id, mapping_id: mapping.mapping_id, name: item.id.replaceAll("_", " "), category: "DATA_QUALITY", executor: "snowflake_sql", execution_support: "AVAILABLE", severity: "ERROR", enabled: item.state !== "DRAFT", archived: false, requires_review: item.state !== "APPROVED", provenance: "TEST_ONLY_UI_FIXTURE", evidence: "TEST_ONLY_UI_FIXTURE", params: { contract: { type: item.id.includes("freshness") ? "FRESHNESS" : item.id.includes("unique") ? "UNIQUENESS" : "COMPLETENESS", column: "order_id" } } }));
  const plan = { plan_id: fixture.scope.plan_id, project_id: fixture.scope.project_id, environment: fixture.scope.environment, analysis_run_id: "analysis_fixture_001", name: "Fixture orders quality plan", status: "APPROVED", revision: 1, created_at: now, updated_at: now, approved_at: now, approved_by: "fixture-reviewer", mappings: [mapping], checks, unmapped: { sources: [], targets: [] }, summary: { checks: checks.length, enabled: checks.filter((item) => item.enabled).length } };
  const runs = fixture.monitoring.states.map((state) => ({ run_id: state.run_id, plan_id: plan.plan_id, plan_revision: 1, status: state.status, started_at: now, completed_at: now, result_count: checks.length, status_counts: state.data_quality_status === "PASS" ? { PASS: checks.length } : state.execution_status === "FAILED" ? { ERROR: checks.length } : { NOT_CHECKED: checks.length }, details_available: true }));
  return { plan, capabilities: { status: "TEST_ONLY_FIXTURE", adapters: ["snowflake_sql"] }, runs, revisions: [], schedules: [], requests: [], automationCapabilities: { status: "TEST_ONLY_FIXTURE" }, runPage: 1, runPageSize: 10, runTotal: runs.length, runHasNext: false, workspace: { projectId: fixture.scope.project_id, environment: fixture.scope.environment } };
}

export async function phase4RunDetail(runId: string): Promise<Record<string, unknown> | null> {
  const workspace = await phase4QualityWorkspace();
  const run = (workspace.runs as Array<Record<string, unknown>>).find((item) => item.run_id === runId);
  if (!run) return null;
  const checks = (workspace.plan as Record<string, unknown>).checks as Array<Record<string, unknown>>;
  return { ...run, results: checks.map((check) => ({ check_id: check.check_id, name: check.name, category: check.category, status: run.status === "COMPLETED" ? "PASS" : run.status === "FAILED" ? "ERROR" : "NOT_CHECKED", result: { source: "TEST_ONLY_UI_FIXTURE" } })) };
}
