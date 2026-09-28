import { currentWorkspaceState, hasCurrentWorkspacePlan, recordMatchesCurrentExecution, resolveWorkspace, workspaceQuery, type CurrentWorkspaceState, type WorkspaceScope } from "../../../lib/server-workspace";
import { matchesCurrentQualityPlan, qualityRunsForPlan, qualityRunsForTable } from "../../../lib/operations-quality-scope";

export const dynamic = "force-dynamic";

const API_BASE = process.env.ADE_API_BASE_URL ?? "http://127.0.0.1:8011";

const overviewCache = new Map<string, { expiresAt: number; value: Record<string, unknown> }>();
const overviewInflight = new Map<string, Promise<Record<string, unknown>>>();

type JsonRecord = Record<string, unknown>;

async function read(endpoint: string, timeoutMs = 4000): Promise<Record<string, unknown>> {
  try {
    const response = await fetch(`${API_BASE}${endpoint}`, { cache: "no-store", signal: AbortSignal.timeout(timeoutMs) });
    const value = await response.json().catch(() => ({})) as Record<string, unknown>;
    return response.ok ? value : { status: "ERROR", reason: value.detail ?? `HTTP ${response.status}` };
  } catch (error) {
    return { status: "ERROR", reason: error instanceof Error ? error.message : "Request failed" };
  }
}

async function qualityHistory(scope: WorkspaceScope, sourceTableScopeId: string): Promise<JsonRecord> {
  if (!sourceTableScopeId) return { status: "NO_ACTIVE_SCOPE", count: 0, items: [], complete: true, unscoped_count: 0 };
  const pageSize = 100;
  const maxPages = 10;
  const items: unknown[] = [];
  let page = 1;
  let hasNext = false;
  let unavailable = false;
  do {
    const params = new URLSearchParams({ project_id: scope.projectId, environment: scope.environment, page: String(page), page_size: String(pageSize) });
    const response = await read(`/api/v1/quality-runs?${params.toString()}`);
    if (response.status === "ERROR") {
      unavailable = true;
      break;
    }
    if (Array.isArray(response.items)) items.push(...response.items);
    hasNext = Boolean(response.has_next);
    page += 1;
  } while (hasNext && page <= maxPages);

  const scopedItems = qualityRunsForTable(items, sourceTableScopeId);
  const unscopedCount = items.filter((item) => item && typeof item === "object" && !Array.isArray(item)
    && !String((item as JsonRecord).source_table_scope_id ?? (item as JsonRecord).sourceTableScopeId ?? "").trim()).length;
  const complete = !hasNext && !unavailable;
  return {
    status: unavailable ? (items.length ? "PARTIAL" : "UNAVAILABLE") : "AVAILABLE",
    count: scopedItems.length,
    items: scopedItems.slice(0, 10),
    latest: scopedItems[0] ?? null,
    complete,
    unscoped_count: unscopedCount,
  };
}

async function qualityPlanState(scope: WorkspaceScope, state: CurrentWorkspaceState, query: string) {
  if (!state.sourceTableScopeId || !state.selectedSourceTable) {
    return { plan: {}, plan_state: "NO_ACTIVE_SCOPE", runs: { status: "NO_ACTIVE_SCOPE", count: 0, items: [] }, history: await qualityHistory(scope, "") };
  }
  const historyPromise = qualityHistory(scope, state.sourceTableScopeId);
  // Quality-plan persistence is independent of the UI's onboarding progress
  // markers. Resolve the plan for the exact current project/environment/table
  // scope and validate its immutable envelope below. A missing local
  // `qualityPlanScopeId` must not hide an existing scoped plan from Overview.
  const candidatePlan = await read(`/api/v1/quality-plans/latest?${query}`);
  if (candidatePlan.status === "ERROR") {
    return { plan: {}, plan_state: "UNAVAILABLE", runs: { status: "UNAVAILABLE", count: 0, items: [] }, history: await historyPromise };
  }
  if (!matchesCurrentQualityPlan(candidatePlan, scope, state)) {
    const hasOtherPlan = Boolean(candidatePlan.plan_id);
    return { plan: {}, plan_state: hasOtherPlan ? "OTHER_SCOPE" : "NOT_GENERATED", runs: { status: "NOT_RUN", count: 0, items: [] }, history: await historyPromise };
  }
  const planId = String(candidatePlan.plan_id ?? "");
  const [runResponse, history] = await Promise.all([
    read(`/api/v1/quality-plans/${encodeURIComponent(planId)}/runs`),
    historyPromise,
  ]);
  const currentPlanRuns = runResponse.status === "ERROR" ? [] : qualityRunsForPlan(Array.isArray(runResponse.items) ? runResponse.items : [], planId);
  return {
    plan: candidatePlan,
    plan_state: "AVAILABLE",
    runs: { status: runResponse.status === "ERROR" ? "UNAVAILABLE" : "AVAILABLE", count: currentPlanRuns.length, items: currentPlanRuns },
    history,
  };
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
    const hasEvidence = await hasCurrentWorkspacePlan(scope);
    const quality = await qualityPlanState(scope, state, query);
    const runIds = new Set(Array.isArray((quality.runs as JsonRecord).items) ? ((quality.runs as JsonRecord).items as JsonRecord[]).flatMap((item) => typeof item.run_id === "string" ? [item.run_id] : []) : []);
    const incidents = value.incidents && typeof value.incidents === "object" ? value.incidents as Record<string, unknown> : {};
    const alerts = value.alerts && typeof value.alerts === "object" ? value.alerts as Record<string, unknown> : {};
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
      ...quality,
      incidents: { count: currentIncidents.length, items: currentIncidents },
      alerts: { count: currentAlerts.length, items: currentAlerts },
      agent: value.agent ?? { status: "NOT_INVOKED" },
      execution: { runCount: runIds.size },
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
  const quality = await qualityPlanState(scope, currentState, query);
  const currentRunIds = new Set(Array.isArray((quality.runs as JsonRecord).items) ? ((quality.runs as JsonRecord).items as JsonRecord[]).flatMap((item) => typeof item.run_id === "string" ? [item.run_id] : []) : []);
  const currentIncidents = Array.isArray(incidents.items) ? incidents.items.filter((item) => recordMatchesCurrentExecution(item, currentState, currentRunIds)) : [];
  const incidentIds = new Set(currentIncidents.flatMap((item) => item && typeof item === "object" && typeof (item as Record<string, unknown>).incident_id === "string" ? [(item as Record<string, unknown>).incident_id as string] : []));
  const currentAlerts = Array.isArray(alerts.items) ? alerts.items.filter((item) => item && typeof item === "object" && incidentIds.has(String((item as Record<string, unknown>).incident_id ?? ""))) : [];
  return Response.json({ generatedAt: new Date().toISOString(), workspace: scope, source_table_scope_id: currentState.sourceTableScopeId || null, integrations: { postgres, snowflake, airflow, dbt }, analysis, ...quality, incidents: { count: currentIncidents.length, items: currentIncidents }, alerts: { count: currentAlerts.length, items: currentAlerts }, agent, execution: { runCount: currentRunIds.size } }, { headers: { "Cache-Control": "no-store" } });
}
