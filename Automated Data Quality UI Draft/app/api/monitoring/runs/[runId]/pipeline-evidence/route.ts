import { resolveWorkspace, workspaceQuery } from "../../../../../../lib/server-workspace";

export const dynamic = "force-dynamic";

const API_BASE = process.env.ADE_API_BASE_URL ?? "http://127.0.0.1:8011";

export async function GET(request: Request, { params }: { params: Promise<{ runId: string }> }) {
  try {
    const scope = await resolveWorkspace(request);
    const { runId } = await params;
    const headers = new Headers({ "x-ade-project-id": scope.projectId });
    const apiKey = request.headers.get("x-ade-api-key") ?? process.env.ADE_UI_API_KEY;
    if (apiKey) headers.set("x-ade-api-key", apiKey);
    const response = await fetch(`${API_BASE}/api/v1/actions/runs/${encodeURIComponent(runId)}/pipeline-evidence?${workspaceQuery(scope)}`, {
      headers, cache: "no-store", signal: AbortSignal.timeout(12000),
    });
    const value = await response.json().catch(() => ({}));
    return Response.json(value, { status: response.status, headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return Response.json({ status: "UNAVAILABLE", reason: error instanceof Error ? error.message : "Pipeline evidence could not be loaded" }, { status: 504 });
  }
}
