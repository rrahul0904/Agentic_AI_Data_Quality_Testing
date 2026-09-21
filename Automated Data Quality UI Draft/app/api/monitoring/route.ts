import { resolveWorkspace, workspaceQuery } from "../../../lib/server-workspace";

export const dynamic = "force-dynamic";

const API_BASE = process.env.ADE_API_BASE_URL ?? "http://127.0.0.1:8011";

export async function GET(request: Request) {
  try {
    const scope = await resolveWorkspace(request);
    const incoming = new URL(request.url).searchParams;
    const query = new URLSearchParams(workspaceQuery(scope));
    for (const key of ["status", "technology", "asset", "since", "until", "page", "page_size"]) {
      const value = incoming.get(key);
      if (value) query.set(key, value);
    }
    const headers = new Headers({ "x-ade-project-id": scope.projectId });
    const apiKey = request.headers.get("x-ade-api-key") ?? process.env.ADE_UI_API_KEY;
    if (apiKey) headers.set("x-ade-api-key", apiKey);
    const response = await fetch(`${API_BASE}/api/v1/monitoring?${query}`, { cache: "no-store", headers, signal: AbortSignal.timeout(4000) });
    const value = await response.json().catch(() => ({}));
    const hasExplicitAsset = Boolean(incoming.get("asset"));
    const items = Array.isArray((value as Record<string, unknown>).items) ? (value as Record<string, unknown>).items as unknown[] : [];
    const status = response.ok && hasExplicitAsset && items.length === 0
      ? "NO_MATCHING_ASSET_FILTER"
      : response.ok && items.length === 0
        ? "NO_RUNS"
        : value.status;
    return Response.json({ ...value, ...(status ? { status } : {}), workspace: scope }, { status: response.status, headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Monitoring is temporarily unavailable" }, { status: 504 });
  }
}
