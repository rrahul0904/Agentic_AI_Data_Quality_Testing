import { acceptedAssetCount } from "../../../lib/catalog-coverage";
import { onboardedTableCount, runtimeIncorporationNote, liveCatalogTableCount } from "../../../lib/project-scope-contract";
import { currentWorkspaceState, projectWorkflowSnapshot, resolveWorkspace, workspaceQuery } from "../../../lib/server-workspace";
import type { AnalysisNode } from "../../../lib/project-analysis";
import { isPhase4Fixture, phase3ProjectScope } from "../../../lib/server-test-fixture";

export const dynamic = "force-dynamic";

const API_BASE = process.env.ADE_API_BASE_URL ?? "http://127.0.0.1:8011";
type RecordValue = Record<string, unknown>;
function isRecord(value: unknown): value is RecordValue { return !!value && typeof value === "object" && !Array.isArray(value); }

async function read(endpoint: string): Promise<RecordValue> {
  try {
    const response = await fetch(`${API_BASE}${endpoint}`, { cache: "no-store", signal: AbortSignal.timeout(6500) });
    const body = await response.json().catch(() => ({})) as RecordValue;
    return response.ok ? body : { status: "UNAVAILABLE", reason: `HTTP ${response.status}` };
  } catch {
    return { status: "UNAVAILABLE" };
  }
}

function inventoryCount(value: RecordValue): number | null {
  const state = String(value.status ?? "").toUpperCase();
  const extensions = isRecord(value.extensions) ? value.extensions : {};
  const tableEntries = Array.isArray(extensions.tables) ? extensions.tables : null;
  const direct = value.table_count ?? value.count;
  const entries = ["tables", "objects", "items"].map((key) => value[key]).find(Array.isArray);
  return liveCatalogTableCount(state, tableEntries ? tableEntries.length : typeof direct === "number" ? direct : Array.isArray(entries) ? entries.length : null);
}

function timestamp(value: unknown): number {
  if (typeof value !== "string") return 0;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export async function GET(request: Request) {
  try {
    if (isPhase4Fixture(request)) return Response.json(phase3ProjectScope(), { headers: { "Cache-Control": "no-store", "X-ADQ-Test-Fixture": "phase4" } });
    const workspace = await resolveWorkspace(request);
    const state = await currentWorkspaceState(workspace);
    const workflow = await projectWorkflowSnapshot(workspace);
    const savedTablesRaw = Array.isArray(workflow?.selectedSourceTables)
      ? workflow.selectedSourceTables.filter((item): item is RecordValue => !!item && typeof item === "object")
      : workflow?.selectedSourceTable && typeof workflow.selectedSourceTable === "object"
        ? [workflow.selectedSourceTable as RecordValue]
        : [];
    const savedTables = savedTablesRaw.map((table, index) => ({
      id: String(table.id ?? `saved-${index}`),
      database: String(table.database ?? ""),
      schema: String(table.schema ?? ""),
      table: String(table.table ?? table.name ?? ""),
      columns: Array.isArray(table.columns) ? table.columns : [],
    }));
    const params = new URLSearchParams(workspaceQuery(workspace));
    if (state.sourceTableScopeId) params.set("source_table_scope_id", state.sourceTableScopeId);
    const connectorParams = new URLSearchParams({ project_id: workspace.projectId, environment: workspace.environment });
    const [postgres, snowflake, analysis, actionRuns] = await Promise.all([
      read(`/api/v1/connections/postgres/metadata?${connectorParams}`),
      read(`/api/v1/connections/snowflake/metadata?${connectorParams}`),
      state.sourceTableScopeId ? read(`/api/v1/project-analysis/latest?${params}&view=compact`) : Promise.resolve({} as RecordValue),
      read(`/api/v1/actions/runs?${connectorParams}&limit=100`),
    ]);
    const report = isRecord(analysis.report) ? analysis.report : analysis;
    const reportScopeMatches = String(report.project_id ?? report.projectId ?? "").toLowerCase() === workspace.projectId.toLowerCase()
      && String(report.environment ?? "").toLowerCase() === workspace.environment.toLowerCase()
      && String(report.source_table_scope_id ?? report.sourceTableScopeId ?? "").toLowerCase() === state.sourceTableScopeId.toLowerCase();
    const graph = reportScopeMatches && report.graph && typeof report.graph === "object" ? report.graph as RecordValue : {};
    const graphNodes = Array.isArray(graph.nodes) ? graph.nodes.filter((node): node is RecordValue => isRecord(node) && isRecord(node.properties) && node.properties.is_top_level !== false) : [];
    const pipelines = reportScopeMatches && Array.isArray(report.pipelines) ? report.pipelines : [];
    const runtime = reportScopeMatches && report.runtime && typeof report.runtime === "object" ? report.runtime as RecordValue : {};
    const runs = Array.isArray(actionRuns.items) ? actionRuns.items.filter((item): item is RecordValue => !!item && typeof item === "object") : [];
    const projectRuns = runs.filter((item) => {
      const plan = item.plan && typeof item.plan === "object" ? item.plan as RecordValue : item;
      return String(plan.project_id ?? plan.projectId ?? "").toLowerCase() === workspace.projectId.toLowerCase()
        && String(plan.environment ?? "").toLowerCase() === workspace.environment.toLowerCase();
    });
    const latestActionRun = projectRuns.sort((left, right) => timestamp(String(right.completed_at ?? right.started_at ?? "")) - timestamp(String(left.completed_at ?? left.started_at ?? "")))[0] ?? null;
    const latestPlan = latestActionRun?.plan && typeof latestActionRun.plan === "object" ? latestActionRun.plan as RecordValue : latestActionRun;
    const latestActionIsScoped = Boolean(latestPlan && String(latestPlan.source_table_scope_id ?? latestPlan.sourceTableScopeId ?? "") === state.sourceTableScopeId && state.sourceTableScopeId);
    const refreshedAt = typeof runtime.refreshed_at === "string" ? runtime.refreshed_at : null;
    const latestRunAt = latestActionRun ? String(latestActionRun.completed_at ?? latestActionRun.started_at ?? "") : "";
    const runtimeNote = latestActionRun && !latestActionIsScoped
      ? `A project/environment action run exists (${String(latestActionRun.run_id ?? "run ID unavailable")}), but its plan has no binding to the active source table. It is not counted in this table's lineage; no table scope is inferred. ${refreshedAt ? `The last scoped runtime refresh was ${refreshedAt}.` : "No table-scoped runtime refresh is saved."}`
      : runtimeIncorporationNote({ refreshedAt, latestRunAt, observedEdges: typeof runtime.observed_edge_count === "number" ? runtime.observed_edge_count : null });
    const notIncorporatedRuns = projectRuns.filter((item) => {
      const plan = item.plan && typeof item.plan === "object" ? item.plan as RecordValue : item;
      return !String(plan.source_table_scope_id ?? plan.sourceTableScopeId ?? "");
    }).map((item) => ({
      run_id: String(item.run_id ?? ""),
      state: String(item.state ?? item.status ?? "UNKNOWN"),
      external_identifiers: Array.isArray(item.external_identifiers) ? item.external_identifiers : [],
      reason: "Action plan is not bound to the active source-table scope; not attributed by name.",
    }));
    const observedNodes = typeof runtime.observed_node_count === "number" ? Math.max(0, runtime.observed_node_count) : null;
    const observedEdges = typeof runtime.observed_edge_count === "number" ? Math.max(0, runtime.observed_edge_count) : null;
    return Response.json({
      workspace,
      source_table_scope_id: state.sourceTableScopeId || null,
      active_source_table: state.selectedSourceTable,
      available_source_tables: inventoryCount(postgres),
      available_source_status: String(postgres.status ?? "UNAVAILABLE"),
      onboarded_source_tables: onboardedTableCount(savedTables),
      accepted_discovered_assets: reportScopeMatches ? acceptedAssetCount(graphNodes as unknown as AnalysisNode[]) : null,
      analyzed_source_rooted_flows: reportScopeMatches ? pipelines.length : null,
      runtime_verified_assets: observedNodes,
      runtime_verified_edges: observedEdges,
      runtime_refreshed_at: refreshedAt,
      runtime_note: runtimeNote,
      execution_evidence_not_incorporated: notIncorporatedRuns,
      analysis_scope_current: reportScopeMatches,
      unavailable_connectors: [postgres.status === "UNAVAILABLE" ? "PostgreSQL catalog" : null, snowflake.status === "UNAVAILABLE" ? "Snowflake catalog" : null].filter(Boolean),
    }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Unable to load project scope counts" }, { status: 502, headers: { "Cache-Control": "no-store" } });
  }
}
