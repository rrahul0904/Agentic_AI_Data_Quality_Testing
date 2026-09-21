import { currentWorkspaceRunIds, currentWorkspaceState, hasCurrentWorkspacePlan, recordMatchesCurrentExecution, resolveWorkspace, workspaceQuery } from "../../../lib/server-workspace";

export const dynamic = "force-dynamic";

const API_BASE = process.env.ADE_API_BASE_URL ?? "http://127.0.0.1:8011";

async function backend(endpoint: string): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE}${endpoint}`, { cache: "no-store", signal: AbortSignal.timeout(30000) });
  const value = await response.json().catch(() => ({})) as Record<string, unknown>;
  if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : `ADE API returned ${response.status}`);
  return value;
}

export async function GET(request: Request) {
  try {
    const scope = await resolveWorkspace(request);
    if (!(await hasCurrentWorkspacePlan(scope))) {
      return Response.json({ investigations: { count: 0, incidents: [] }, workspace: scope }, { headers: { "Cache-Control": "no-store" } });
    }
    const query = workspaceQuery(scope);
    const [state, runIds, investigations] = await Promise.all([
      currentWorkspaceState(scope),
      currentWorkspaceRunIds(scope),
      backend(`/api/v1/investigations?limit=100&${query}`),
    ]);
    const items = Array.isArray(investigations.incidents) ? investigations.incidents.filter((item) => recordMatchesCurrentExecution(item, state, runIds)) : [];
    return Response.json({ investigations: { ...investigations, count: items.length, incidents: items }, workspace: scope }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Unable to load investigations" }, { status: 502 });
  }
}
