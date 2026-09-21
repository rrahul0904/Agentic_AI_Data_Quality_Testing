export const dynamic = "force-dynamic";

import { currentWorkspaceState, resolveWorkspace } from "../../../lib/server-workspace";

const API_BASE = process.env.ADE_API_BASE_URL ?? "http://127.0.0.1:8011";

function backendHeaders(request: Request, projectId: string, contentType = false): Headers {
  const headers = new Headers();
  if (contentType) headers.set("content-type", "application/json");
  for (const name of ["x-ade-api-key", "x-ade-identity"]) {
    const value = request.headers.get(name) ?? (name === "x-ade-api-key" ? process.env.ADE_UI_API_KEY : undefined);
    if (value) headers.set(name, value);
  }
  headers.set("x-ade-project-id", projectId);
  return headers;
}

export async function GET(request: Request) {
  try {
    const workspace = await resolveWorkspace(request);
    const currentState = await currentWorkspaceState(workspace);
    const [statusResponse, rosterResponse] = await Promise.all([
      fetch(`${API_BASE}/api/v1/agent/status`, { headers: backendHeaders(request, workspace.projectId), cache: "no-store", signal: AbortSignal.timeout(30000) }),
      fetch(`${API_BASE}/api/v1/agents/roster`, { headers: backendHeaders(request, workspace.projectId), cache: "no-store", signal: AbortSignal.timeout(30000) }),
    ]);
    const status = await statusResponse.json() as Record<string, unknown>;
    const roster = await rosterResponse.json().catch(() => ({})) as Record<string, unknown>;
    const activity = Array.isArray(status.agent_activity)
      ? status.agent_activity.filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
      : [];
    const specialists = Array.isArray(roster.agents) ? roster.agents.map((item) => {
      if (!item || typeof item !== "object") return item;
      const agent = item as Record<string, unknown>;
      const role = String(agent.role ?? "");
      const invocation = activity.find((entry) => String(entry.role ?? "").startsWith(role) || role.startsWith(String(entry.role ?? "").split("_")[0]));
      return { ...agent, invocation_status: invocation ? String(invocation.status ?? "INVOKED") : "NOT INVOKED", invocation_role: invocation?.role ?? null };
    }) : [];
    return Response.json({ ...status, workspace, source_table_scope_id: currentState.sourceTableScopeId || null, specialists, agent_activity: activity, roster_status: roster.status ?? "UNAVAILABLE", scope_mode: currentState.sourceTableScopeId ? "OPTIONAL_TABLE_CONTEXT" : "PROJECT_ONLY" }, { status: statusResponse.status });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Unable to load agent status" }, { status: 502 });
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json() as { question?: string; selected_asset?: string; run_id?: string; context?: Record<string, unknown> };
    const workspace = await resolveWorkspace(request);
    const response = await fetch(`${API_BASE}/api/v1/agent/query`, {
      method: "POST", headers: backendHeaders(request, workspace.projectId, true),
      body: JSON.stringify({
        question: body.question,
        project_id: workspace.projectId,
        environment: workspace.environment,
        selected_asset: body.selected_asset || null,
        run_id: body.run_id || null,
        context: body.context || {},
      }),
      cache: "no-store", signal: AbortSignal.timeout(120000),
    });
    const value = await response.json().catch(() => ({}));
    return Response.json(value, { status: response.status });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Agent query failed" }, { status: 502 });
  }
}
