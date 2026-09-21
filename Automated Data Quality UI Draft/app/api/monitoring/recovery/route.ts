import { resolveWorkspace, workspaceQuery } from "../../../../lib/server-workspace";

export const dynamic = "force-dynamic";

const API_BASE = process.env.ADE_API_BASE_URL ?? "http://127.0.0.1:8011";

export async function GET(request: Request) {
  try {
    const scope = await resolveWorkspace(request);
    const incoming = new URL(request.url).searchParams;
    const query = new URLSearchParams(workspaceQuery(scope));
    query.set("limit", incoming.get("limit") ?? "50");
    const headers = new Headers({ "x-ade-project-id": scope.projectId });
    const apiKey = request.headers.get("x-ade-api-key") ?? process.env.ADE_UI_API_KEY;
    if (apiKey) headers.set("x-ade-api-key", apiKey);
    const response = await fetch(`${API_BASE}/api/v1/actions/recovery-queue?${query}`, {
      cache: "no-store",
      headers,
      signal: AbortSignal.timeout(4000),
    });
    const value = await response.json().catch(() => ({}));
    return Response.json({ ...value, workspace: scope }, { status: response.status, headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Recovery queue is temporarily unavailable" }, { status: 504 });
  }
}
