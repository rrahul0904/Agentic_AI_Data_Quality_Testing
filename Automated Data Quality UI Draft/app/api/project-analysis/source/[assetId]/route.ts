import { hasCurrentWorkspaceAnalysis, resolveWorkspace, workspaceQuery } from "../../../../../lib/server-workspace";

export const dynamic = "force-dynamic";

const API_BASE = process.env.ADE_API_BASE_URL ?? "http://127.0.0.1:8011";

export async function GET(request: Request, context: { params: Promise<{ assetId: string }> }) {
  try {
    const { assetId } = await context.params;
    const scope = await resolveWorkspace(request);
    if (!(await hasCurrentWorkspaceAnalysis(scope))) {
      return Response.json({ error: "Run current one-table analysis before opening object evidence." }, { status: 409 });
    }
    const response = await fetch(
      `${API_BASE}/api/v1/project-analysis/assets/${encodeURIComponent(assetId)}/source?${workspaceQuery(scope)}`,
      { cache: "no-store", signal: AbortSignal.timeout(15000) },
    );
    const body = await response.json().catch(() => ({})) as Record<string, unknown>;
    if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : `ADE API returned ${response.status}`);
    return Response.json(body, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Unable to load asset source" }, { status: 502 });
  }
}
