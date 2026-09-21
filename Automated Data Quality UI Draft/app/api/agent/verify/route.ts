export const dynamic = "force-dynamic";

import { resolveWorkspace, workspaceQuery } from "../../../../lib/server-workspace";

const API_BASE = process.env.ADE_API_BASE_URL ?? "http://127.0.0.1:8011";

export async function POST(request: Request) {
  try {
    const workspace = await resolveWorkspace(request);
    const body = await request.json().catch(() => ({})) as Record<string, unknown>;
    const headers = new Headers({ "content-type": "application/json", "x-ade-project-id": workspace.projectId });
    const apiKey = request.headers.get("x-ade-api-key") ?? process.env.ADE_UI_API_KEY;
    if (apiKey) headers.set("x-ade-api-key", apiKey);
    const response = await fetch(`${API_BASE}/api/v1/agent/verify-provider?${workspaceQuery(workspace)}`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        project_id: workspace.projectId,
        environment: workspace.environment,
        selected_asset: typeof body.selected_asset === "string" ? body.selected_asset : null,
        run_id: typeof body.run_id === "string" ? body.run_id : null,
      }),
      cache: "no-store",
      signal: AbortSignal.timeout(30000),
    });
    const value = await response.json().catch(() => ({}));
    return Response.json({ ...value, workspace }, { status: response.status, headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return Response.json({ status: "FAILED", evidence_state: "failed", reason: error instanceof Error ? error.message : "Provider verification failed" }, { status: 502 });
  }
}
