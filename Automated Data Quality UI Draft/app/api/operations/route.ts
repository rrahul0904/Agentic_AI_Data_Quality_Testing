import { currentWorkspaceRunIds, currentWorkspaceState, hasCurrentWorkspacePlan, recordMatchesCurrentExecution, recordMatchesCurrentTable, resolveWorkspace, workspaceQuery, type WorkspaceScope } from "../../../lib/server-workspace";

export const dynamic = "force-dynamic";

const API_BASE = process.env.ADE_API_BASE_URL ?? "http://127.0.0.1:8011";

const overviewCache = new Map<string, { expiresAt: number; value: Record<string, unknown> }>();
const overviewInflight = new Map<string, Promise<Record<string, unknown>>>();

async function read(endpoint: string, timeoutMs = 4000): Promise<Record<string, unknown>> {
  try {
    const response = await fetch(`${API_BASE}${endpoint}`, { cache: "no-store", signal: AbortSignal.timeout(timeoutMs) });
    const value = await response.json().catch(() => ({})) as Record<string, unknown>;
    return response.ok ? value : { status: "ERROR", reason: value.detail ?? `HTTP ${response.status}` };
  } catch (error) {
    return { status: "ERROR", reason: error instanceof Error ? error.message : "Request failed" };
  }
}

async function persistedOverview(query: string, scope: WorkspaceScope, accessContext: string): Promise<Record<string, unknown>> {
  const key = `${query}|access:${accessContext || "local"}`;
  const cached = overviewCache.get(key);
  if (cached && cached.expiresAt > Date.now()) return cached.value;
  const active = overviewInflight.get(key);
  if (active) return active;
  const pending = (async () => {
    const value = await read(`/api/v1/operations/overview?${query}`, 2500);
    const state = await currentWorkspaceState(scope);
    const hasActiveTable = Boolean(state.sourceTableScopeId && state.selectedSourceTable);
    const runIds = await currentWorkspaceRunIds(scope);
    const runs = value.runs && typeof value.runs === "object" ? value.runs as Record<string, unknown> : {};
    const incidents = value.incidents && typeof value.incidents === "object" ? value.incidents as Record<string, unknown> : {};
    const alerts = value.alerts && typeof value.alerts === "object" ? value.alerts as Record<string, unknown> : {};
    const currentRuns = Array.isArray(runs.items)
      ? runs.items.filter((item) => item && typeof item === "object" && typeof (item as Record<string, unknown>).run_id === "string" && runIds.has((item as Record<string, unknown>).run_id as string))
      : [];
    const currentIncidents = Array.isArray(incidents.items) ? incidents.items.filter((item) => recordMatchesCurrentExecution(item, state, runIds)) : [];
    const incidentIds = new Set(currentIncidents.flatMap((item) => item && typeof item === "object" && typeof (item as Record<string, unknown>).incident_id === "string" ? [(item as Record<string, unknown>).incident_id as string] : []));
    const currentAlerts = Array.isArray(alerts.items)
      ? alerts.items.filter((item) => item && typeof item === "object" && incidentIds.has(String((item as Record<string, unknown>).incident_id ?? "")))
      : [];
    const result = {
      generatedAt: value.generated_at ?? new Date().toISOString(),
      workspace: scope,
      source_table_scope_id: state.sourceTableScopeId || null,
      integrations: value.integrations ?? {},
      analysis: hasActiveTable ? value.analysis ?? { status: "NOT_RUN", summary: {} } : { status: "NOT_RUN", summary: {}, count: 0, items: [] },
      plan: hasActiveTable ? value.plan ?? { summary: {} } : { summary: {} },
      runs: { count: currentRuns.length, items: currentRuns },
      incidents: { count: currentIncidents.length, items: currentIncidents },
      alerts: { count: currentAlerts.length, items: currentAlerts },
      agent: value.agent ?? { status: "NOT_INVOKED" },
      execution: { runCount: currentRuns.length },
      refresh: "BACKGROUND",
      source: value.source ?? "PERSISTED_CONTROL_PLANE",
    } as Record<string, unknown>;
    overviewCache.set(key, { expiresAt: Date.now() + 10_000, value: result });
    return result;
  })().finally(() => overviewInflight.delete(key));
  overviewInflight.set(key, pending);
  return pending;
}

export async function GET(request: Request) {
  const scope = await resolveWorkspace(request);
  const mode = new URL(request.url).searchParams.get("mode");
  const currentState = await currentWorkspaceState(scope);
  const scopedQuery = new URLSearchParams(workspaceQuery(scope));
  if (currentState.sourceTableScopeId) scopedQuery.set("source_table_scope_id", currentState.sourceTableScopeId);
  const query = scopedQuery.toString();
  if (mode === "summary") {
    const accessContext = request.headers.get("x-ade-identity") ?? request.headers.get("x-ade-project-id") ?? "local";
    return Response.json(await persistedOverview(query, scope, accessContext), { headers: { "Cache-Control": "no-store" } });
  }
  const connectorQuery = new URLSearchParams({ project_id: scope.projectId, environment: scope.environment }).toString();
  const hasEvidence = await hasCurrentWorkspacePlan(scope);
  const [postgres, snowflake, airflow, dbt, analysis, incidents, alerts, agent] = await Promise.all([
    read(`/api/v1/connections/postgres/metadata?${connectorQuery}`),
    read(`/api/v1/connections/snowflake/metadata?${connectorQuery}`),
    read(`/api/v1/connections/airflow/metadata?${connectorQuery}`),
    read(`/api/v1/connections/dbt/state?${connectorQuery}`),
    hasEvidence ? read(`/api/v1/project-analysis/latest?${query}`) : Promise.resolve({ status: "NOT_RUN", summary: {}, count: 0, items: [] }),
    hasEvidence ? read(`/api/v1/quality-operations/incidents?${query}`) : Promise.resolve({ count: 0, items: [] }),
    hasEvidence ? read(`/api/v1/quality-operations/alerts?${query}`) : Promise.resolve({ count: 0, items: [] }),
    read("/api/v1/agent/status"),
  ]);
  const candidatePlan = hasEvidence ? await read(`/api/v1/quality-plans/latest?${query}`) : {};
  const plan = hasEvidence && recordMatchesCurrentTable(candidatePlan, currentState) ? candidatePlan : {};
  const runs = plan.plan_id ? await read(`/api/v1/quality-plans/${String(plan.plan_id)}/runs`) : { count: 0, items: [] };
  const currentRunIds = new Set(Array.isArray(runs.items) ? runs.items.flatMap((item) => item && typeof item === "object" && typeof (item as Record<string, unknown>).run_id === "string" ? [(item as Record<string, unknown>).run_id as string] : []) : []);
  const currentIncidents = Array.isArray(incidents.items) ? incidents.items.filter((item) => recordMatchesCurrentExecution(item, currentState, currentRunIds)) : [];
  const incidentIds = new Set(currentIncidents.flatMap((item) => item && typeof item === "object" && typeof (item as Record<string, unknown>).incident_id === "string" ? [(item as Record<string, unknown>).incident_id as string] : []));
  const currentAlerts = Array.isArray(alerts.items) ? alerts.items.filter((item) => item && typeof item === "object" && incidentIds.has(String((item as Record<string, unknown>).incident_id ?? ""))) : [];
  return Response.json({ generatedAt: new Date().toISOString(), workspace: scope, source_table_scope_id: currentState.sourceTableScopeId || null, integrations: { postgres, snowflake, airflow, dbt }, analysis, plan, runs, incidents: { count: currentIncidents.length, items: currentIncidents }, alerts: { count: currentAlerts.length, items: currentAlerts }, agent, execution: { runCount: currentRunIds.size } }, { headers: { "Cache-Control": "no-store" } });
}
