export const dynamic = "force-dynamic";

import { resolveWorkspace } from "../../../../lib/server-workspace";

const API_BASE = process.env.ADE_API_BASE_URL ?? "http://127.0.0.1:8011";

function backendHeaders(request: Request, projectId: string): Headers {
  const headers = new Headers();
  for (const name of ["x-ade-api-key", "x-ade-identity"]) {
    const value = request.headers.get(name) ?? (name === "x-ade-api-key" ? process.env.ADE_UI_API_KEY : undefined);
    if (value) headers.set(name, value);
  }
  headers.set("x-ade-project-id", projectId);
  return headers;
}

export async function GET(request: Request, context: { params: Promise<{ evidenceId: string }> }) {
  try {
    const workspace = await resolveWorkspace(request);
    const { evidenceId } = await context.params;
    const incoming = new URL(request.url);
    const target = new URL(`${API_BASE}/api/v1/evidence/${encodeURIComponent(evidenceId)}`);
    for (const key of ["project_id", "environment", "asset_id", "local_run_id"]) {
      const value = incoming.searchParams.get(key);
      if (value) target.searchParams.set(key, value);
    }
    if (!target.searchParams.has("project_id")) target.searchParams.set("project_id", workspace.projectId);
    if (!target.searchParams.has("environment")) target.searchParams.set("environment", workspace.environment);
    const response = await fetch(target, { headers: backendHeaders(request, workspace.projectId), cache: "no-store", signal: AbortSignal.timeout(30000) });
    const body = await response.arrayBuffer();
    return new Response(body, { status: response.status, headers: { "content-type": response.headers.get("content-type") ?? "application/json", "cache-control": "no-store" } });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Evidence could not be loaded" }, { status: 502 });
  }
}
