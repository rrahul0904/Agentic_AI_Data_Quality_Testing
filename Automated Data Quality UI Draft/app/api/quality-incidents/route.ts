import { currentWorkspaceRunIds, currentWorkspaceState, hasCurrentWorkspacePlan, recordMatchesCurrentExecution, resolveWorkspace, workspaceQuery } from "../../../lib/server-workspace";

export const dynamic = "force-dynamic";

const API_BASE = process.env.ADE_API_BASE_URL ?? "http://127.0.0.1:8011";

async function backend(endpoint: string, init?: RequestInit, timeoutMs = 30000): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE}${endpoint}`, { ...init, cache: "no-store", signal: AbortSignal.timeout(timeoutMs) });
  const value = await response.json().catch(() => ({})) as Record<string, unknown>;
  if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : `ADE API returned ${response.status}`);
  return value;
}

export async function GET(request: Request) {
  try {
    const scope = await resolveWorkspace(request);
    const currentState = await currentWorkspaceState(scope);
    if (!currentState.sourceTableScopeId) {
      return Response.json({ incidents: [], alerts: [], capabilities: { status: "NO_ACTIVE_SCOPE" }, workspace: scope, execution: { runCount: 0 } }, { headers: { "Cache-Control": "no-store" } });
    }
    if (!(await hasCurrentWorkspacePlan(scope))) {
      return Response.json({ incidents: [], alerts: [], capabilities: await backend("/api/v1/quality-operations/capabilities"), workspace: scope }, { headers: { "Cache-Control": "no-store" } });
    }
    const query = workspaceQuery(scope);
    const [state, runIds] = await Promise.all([Promise.resolve(currentState), currentWorkspaceRunIds(scope)]);
    const [incidents, alerts, capabilities] = await Promise.all([
      backend(`/api/v1/quality-operations/incidents?${query}`),
      backend(`/api/v1/quality-operations/alerts?${query}`),
      backend("/api/v1/quality-operations/capabilities"),
    ]);
    const currentIncidents = Array.isArray(incidents.items) ? incidents.items.filter((item) => recordMatchesCurrentExecution(item, state, runIds)) : [];
    const incidentIds = new Set(currentIncidents.flatMap((item) => item && typeof item === "object" && typeof (item as Record<string, unknown>).incident_id === "string" ? [(item as Record<string, unknown>).incident_id as string] : []));
    const currentAlerts = Array.isArray(alerts.items) ? alerts.items.filter((item) => item && typeof item === "object" && incidentIds.has(String((item as Record<string, unknown>).incident_id ?? "")) && String((item as Record<string, unknown>).status ?? "").toUpperCase() === "OPEN") : [];
    return Response.json({
      incidents: currentIncidents,
      openCount: currentIncidents.filter((item) => !["RESOLVED", "CERTIFIED"].includes(String((item as Record<string, unknown>).status ?? "").toUpperCase())).length,
      alerts: currentAlerts,
      openAlertCount: currentAlerts.length,
      capabilities,
      workspace: scope,
      execution: { runCount: runIds.size },
    });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Unable to load incidents" }, { status: 502 });
  }
}

export async function POST(request: Request) {
  try {
    const scope = await resolveWorkspace(request);
    const body = await request.json() as Record<string, unknown>;
    const incidentId = String(body.incidentId || "");
    const action = String(body.action || "");
    if (!incidentId || !["approve", "execute", "verify"].includes(action)) {
      return Response.json({ error: "Valid incidentId and action are required" }, { status: 400 });
    }
    const [state, runIds] = await Promise.all([currentWorkspaceState(scope), currentWorkspaceRunIds(scope)]);
    const scopedIncidents = await backend(`/api/v1/quality-operations/incidents?${workspaceQuery(scope)}`);
    const belongsToWorkspace = Array.isArray(scopedIncidents.items)
      && scopedIncidents.items.some((item) => item && typeof (item as Record<string, unknown>).incident_id === "string" && (item as Record<string, unknown>).incident_id === incidentId && recordMatchesCurrentExecution(item, state, runIds));
    if (!belongsToWorkspace) return Response.json({ error: "Incident does not belong to the active project." }, { status: 404 });
    const init: RequestInit = { method: "POST" };
    if (action === "approve") {
      init.headers = { "content-type": "application/json" };
      init.body = JSON.stringify({ approved_by: String(body.approvedBy || "ui-operator") });
    }
    const result = await backend(`/api/v1/quality-operations/incidents/${encodeURIComponent(incidentId)}/${action}`, init, 300000);
    return Response.json({ result });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Incident operation failed" }, { status: 502 });
  }
}
