export const dynamic = "force-dynamic";

import { resolveWorkspace, workspaceQuery } from "../../../lib/server-workspace";

const API_BASE = process.env.ADE_API_BASE_URL ?? "http://127.0.0.1:8011";

function headers(request: Request, workspace: Awaited<ReturnType<typeof resolveWorkspace>>, contentType = false): Headers {
  const value = new Headers();
  if (contentType) value.set("content-type", "application/json");
  value.set("x-ade-project-id", workspace.projectId);
  value.set("x-ade-environment", workspace.environment);
  const apiKey = request.headers.get("x-ade-api-key") ?? process.env.ADE_UI_API_KEY;
  if (apiKey) value.set("x-ade-api-key", apiKey);
  return value;
}

export async function GET(request: Request) {
  try {
    const workspace = await resolveWorkspace(request);
    const response = await fetch(`${API_BASE}/api/v1/ai-provider/config?${workspaceQuery(workspace)}`, { headers: headers(request, workspace), cache: "no-store", signal: AbortSignal.timeout(15000) });
    const value = await response.json().catch(() => ({}));
    return Response.json({ ...value, workspace }, { status: response.status, headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return Response.json({ status: "FAILED", error: error instanceof Error ? error.message : "AI provider settings unavailable" }, { status: 502 });
  }
}

export async function PUT(request: Request) {
  try {
    const workspace = await resolveWorkspace(request);
    const body = await request.json().catch(() => ({})) as Record<string, unknown>;
    const response = await fetch(`${API_BASE}/api/v1/ai-provider/config?${workspaceQuery(workspace)}`, {
      method: "PUT", headers: headers(request, workspace, true), cache: "no-store", signal: AbortSignal.timeout(15000),
      body: JSON.stringify({ ...body, project_id: workspace.projectId, environment: workspace.environment }),
    });
    const value = await response.json().catch(() => ({}));
    return Response.json({ ...value, workspace }, { status: response.status, headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return Response.json({ status: "FAILED", error: error instanceof Error ? error.message : "AI provider settings could not be saved" }, { status: 502 });
  }
}

export async function DELETE(request: Request) {
  try {
    const workspace = await resolveWorkspace(request);
    const response = await fetch(`${API_BASE}/api/v1/ai-provider/config?${workspaceQuery(workspace)}`, { method: "DELETE", headers: headers(request, workspace), cache: "no-store", signal: AbortSignal.timeout(15000) });
    const value = await response.json().catch(() => ({}));
    return Response.json({ ...value, workspace }, { status: response.status, headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return Response.json({ status: "FAILED", error: error instanceof Error ? error.message : "AI provider settings could not be cleared" }, { status: 502 });
  }
}
